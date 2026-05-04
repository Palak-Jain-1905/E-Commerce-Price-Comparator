from django.urls import path
from . import views

urlpatterns = [
    # Main pages
    path('', views.welcome, name='welcome'),
    path('search/', views.compare_prices, name='search'),
    path('result/', views.compare_prices, name='result'),

    # Loading screen
    path('loading/', views.loading_view, name='loading'),

    # Auth
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Product
    path('p/<slug:slug>/', views.product_detail, name='product_detail'),
    path('watch/<slug:slug>/', views.add_watch, name='add_watch'),

    # API
    path('api/suggest/', views.api_suggest, name='api_suggest'),
    path('status/<str:task_id>/', views.task_status, name='task_status'),

    # Misc
    path('tpl-video/<path:filename>/', views.template_video, name='template_video'),
    path('profile/', views.profile_view, name='profile'),
    path('remove-watch/<slug:slug>/', views.remove_watch, name='remove_watch'),

    path('cart/',                    views.cart_view,       name='cart'),
    path('cart/add/<int:offer_id>/', views.add_to_cart,     name='add_to_cart'),
    path('cart/remove/<int:item_id>/',views.remove_from_cart,name='remove_from_cart'),
    path('cart/place-order/',        views.place_order,     name='place_order'),
    path('orders/',                  views.order_history,   name='order_history'),
    path('orders/<int:pk>/',         views.order_detail,    name='order_detail'),
    path('check-alerts/', views.run_price_alerts, name='check_alerts'),
    
    





]