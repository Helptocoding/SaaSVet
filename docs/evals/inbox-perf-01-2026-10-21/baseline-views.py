def _thread_row(conversation, *, session_count, last_message, unanswered):
    """Proyecta la sesión VIGENTE (o la última cerrada) como fila de bandeja."""
    contact = conversation.contact
    handoff = (conversation.handoffs.filter(resolved_at__isnull=True)
               .order_by('-priority', '-id').first())
    archived = conversation.state == Conversation.STATE_CLOSED
    return {
        'contact_public_id': contact.public_id,
        'channel_account_public_id': conversation.channel_account.public_id,
        'contact_display_name': contact.display_name,
        'contact_phone': contact.phone_normalized,
        'contact_verification': contact.verification_level,
        'linked_via': contact.linked_via,
        'owner_name': contact.owner.name if contact.owner_id else None,
        # Archivado: sin sesión vigente y, por tanto, sin acciones. Publicar el
        # `public_id` de una conversación cerrada invitaría a la bandeja a
        # ofrecer «responder» sobre algo que devuelve 400.
        'conversation_public_id': None if archived else conversation.public_id,
        # Entrada privada del serializer: la API publica solo el booleano.
        'processing_until': None if archived else conversation.processing_until,
        'state': None if archived else conversation.state,
        'claimed_by_name': (
            None if archived or conversation.claimed_by_id is None
            else (conversation.claimed_by.get_full_name()
                  or conversation.claimed_by.username)),
        'handoff_priority': handoff.priority if handoff else None,
        'handoff_reason': handoff.reason_code if handoff else None,
        'handoff_detail': handoff.reason_detail if handoff else None,
        'last_activity_at': last_message.created_at if last_message else None,
        'last_message_preview': ((last_message.body or '')[:120]
                                 if last_message else None),
        'has_unanswered': unanswered,
        'session_count': session_count,
    }

def list_threads(request):
    """Bandeja agrupada: una fila por `(contacto, cuenta)`.

    `?archived=1` incluye los hilos sin sesión abierta. Por defecto no salen,
    igual que hoy no salen las conversaciones cerradas.
    """
    from apps.channels.selectors import operational_messages

    org = request.user.organization
    include_archived = request.query_params.get('archived') in ('1', 'true')

    conversations = list(
        Conversation.objects.for_organization(org)
        .select_related('contact', 'contact__owner', 'claimed_by',
                        'channel_account')
        .order_by('-last_activity_at')
    )

    threads = {}
    for conversation in conversations:
        key = (conversation.contact_id, conversation.channel_account_id)
        bucket = threads.setdefault(key, {'sessions': [], 'current': None})
        bucket['sessions'].append(conversation)
        if (bucket['current'] is None
                and conversation.state != Conversation.STATE_CLOSED):
            bucket['current'] = conversation

    rows = []
    for bucket in threads.values():
        sessions = bucket['sessions']
        current = bucket['current']
        if current is None and not include_archived:
            continue
        head = current or sessions[0]      # ordenadas por actividad, desc
        last_message = operational_messages(
            Message.objects.for_organization(org).filter(
                contact_id=head.contact_id,
                channel_account_id=head.channel_account_id)
        ).order_by('-created_at', '-id').first()
        unanswered = bool(
            last_message and last_message.direction == Message.DIRECTION_IN)
        rows.append(_thread_row(head, session_count=len(sessions),
                                last_message=last_message,
                                unanswered=unanswered))

    # Urgentes primero: una convulsión no puede quedar debajo de una duda de
    # horarios más reciente (mismo criterio que la lista por conversación).
    epoch = timezone.make_aware(timezone.datetime(1970, 1, 1))
    rows.sort(
        key=lambda row: (
            row['handoff_priority'] == HumanHandoff.PRIORITY_URGENT,
            row['last_activity_at'] or epoch,
        ),
        reverse=True,
    )
    return Response(ThreadSerializer(rows[:THREADS_CAP], many=True).data)