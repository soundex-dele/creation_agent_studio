from drf_yasg import openapi


api_info = openapi.Info(
    title="Agent Studio API",
    default_version="v1",
    description="API for Agent Studio - a platform for agents, applications, and workflows",
    terms_of_service="https://www.example.com/terms/",
    contact=openapi.Contact(email="contact@example.com"),
    license=openapi.License(name="MIT License"),
)
