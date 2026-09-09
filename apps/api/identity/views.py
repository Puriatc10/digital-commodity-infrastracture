from django.conf import settings
from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from django.contrib.auth import login, logout
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from django.utils.decorators import method_decorator
from rest_framework import status, views, permissions
from rest_framework.response import Response

from .serializers import LoginSerializer, UserSerializer


class LoginView(views.APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = LoginSerializer

    @method_decorator(ensure_csrf_cookie)
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        login(request, user)
        return Response(UserSerializer(user).data, status=status.HTTP_200_OK)


class LogoutView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = None

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class CsrfView(views.APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = None

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return Response({"detail": "CSRF cookie set"})

class DemoPersonaSwitcherRequestSerializer(serializers.Serializer):
    persona = serializers.ChoiceField(choices=["buyer", "supplier", "broker", "operator", "admin"])

class DemoPersonaSwitcherView(views.APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = DemoPersonaSwitcherRequestSerializer

    @extend_schema(responses={200: serializers.ListSerializer(child=serializers.CharField()), 404: str})
    def get(self, request):
        if not getattr(settings, "DEMO_PERSONA_SWITCHER_ENABLED", False):
            raise Http404("Demo persona switcher is disabled")
        return Response(["buyer", "supplier", "broker", "operator", "admin"])

    @extend_schema(request=DemoPersonaSwitcherRequestSerializer, responses={200: UserSerializer, 400: str, 404: str})
    @method_decorator(csrf_protect)
    def post(self, request):
        if not getattr(settings, "DEMO_PERSONA_SWITCHER_ENABLED", False):
            raise Http404("Demo persona switcher is disabled")

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        persona = serializer.validated_data["persona"]

        allowed_personas = {
            "buyer": "buyer@demo.local",
            "supplier": "supplier@demo.local",
            "broker": "broker@demo.local",
            "operator": "operator@demo.local",
            "admin": "admin@demo.local",
        }

        email = allowed_personas[persona]
        from django.contrib.auth import get_user_model
        User = get_user_model()

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"detail": "Demo user not found"}, status=status.HTTP_404_NOT_FOUND)

        login(request, user)
        return Response(UserSerializer(user).data)
