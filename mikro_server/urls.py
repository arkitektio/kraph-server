"""
URL configuration for mikro_server project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.vies import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from strawberry.django.views import AsyncGraphQLView
from .basepath import basepath

from mikro_server.schema import schema

url = "s"

urlpatterns = [
    basepath("admin/", admin.site.urls),
    basepath("graphql", AsyncGraphQLView.as_view(schema=schema)),
    basepath("ht/", include("health_check.urls")),
]
