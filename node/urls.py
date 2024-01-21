from django.urls import include, path

from node import views
app_name='node'

urlpatterns = [
	path('', views.root, name='root'),
]

