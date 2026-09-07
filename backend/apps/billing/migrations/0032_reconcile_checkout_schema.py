from django.db import DatabaseError, migrations


def reconcile_checkout_schema(apps, schema_editor):
    """Complete a partially materialized greenfield schema without data loss."""
    billing_config = apps.get_app_config("billing")
    existing_tables = set(schema_editor.connection.introspection.table_names())
    models = list(billing_config.get_models())

    pending = [model for model in models if model._meta.db_table not in existing_tables]
    while pending:
        progress = False
        for model in pending[:]:
            try:
                schema_editor.create_model(model)
            except DatabaseError:
                continue
            existing_tables.add(model._meta.db_table)
            pending.remove(model)
            progress = True
        if not progress:
            names = ", ".join(model.__name__ for model in pending)
            raise RuntimeError(f"Unable to create billing tables: {names}")

    for model in models:
        table = model._meta.db_table
        cursor = schema_editor.connection.cursor()
        columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor, table
            )
        }
        for field in model._meta.local_concrete_fields:
            if field.column not in columns:
                schema_editor.add_field(model, field)
                columns.add(field.column)


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0031_rename_invoice_void_anchor"),
    ]

    operations = [
        migrations.RunPython(reconcile_checkout_schema, migrations.RunPython.noop),
    ]
