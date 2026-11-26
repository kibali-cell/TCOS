from rest_framework import serializers

from .models import User, UserSession


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(max_length=256, trim_whitespace=False)
    new_password = serializers.CharField(max_length=256, trim_whitespace=False)


class UserProfileSerializer(serializers.ModelSerializer):
    """Own profile. Never includes the password hash or internal security fields."""

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "full_name",
            "email",
            "phone",
            "status",
            "must_change_password",
            "last_login",
        ]
        read_only_fields = fields


class UserSessionSerializer(serializers.ModelSerializer):
    """A signed-in browser or device. The session key is never exposed."""

    is_current = serializers.SerializerMethodField()

    class Meta:
        model = UserSession
        fields = ["id", "device_label", "ip_address", "created_at", "last_seen_at", "is_current"]
        read_only_fields = fields

    def get_is_current(self, obj) -> bool:
        return obj.session_key == self.context.get("current_session_key")


class ForgotPasswordSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=254)


class ResetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=200)
    new_password = serializers.CharField(max_length=256, trim_whitespace=False)


class TwoFactorLoginSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=40)
    recovery = serializers.BooleanField(required=False, default=False)


class CodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=40)


class ReauthSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=256, trim_whitespace=False)
    code = serializers.CharField(max_length=40)
