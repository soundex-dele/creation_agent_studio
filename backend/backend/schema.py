from drf_yasg import openapi


api_info = openapi.Info(
    title="Creation Agent Studio API",
    default_version="v1",
    description="API for Creation Agent Studio - AI-powered video creation platform",
    terms_of_service="https://www.example.com/terms/",
    contact=openapi.Contact(email="contact@example.com"),
    license=openapi.License(name="MIT License"),
)
