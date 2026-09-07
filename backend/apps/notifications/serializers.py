from rest_framework import serializers


class FeedItemSerializer(serializers.Serializer):
    key = serializers.CharField()
    source = serializers.ChoiceField(choices=['persisted', 'derived'])
    type = serializers.CharField()
    priority = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField(allow_blank=True)
    occurred_at = serializers.DateTimeField()
    age_min = serializers.IntegerField()
    seen = serializers.BooleanField()
    active = serializers.BooleanField(default=True)
    entity = serializers.DictField()
