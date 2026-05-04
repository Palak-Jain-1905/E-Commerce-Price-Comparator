from django.contrib import admin
from .models import Product, Offer, PriceHistory, SearchLog, LoginActivity, Wishlist, ResultCount

admin.site.register(Product)
admin.site.register(Offer)
admin.site.register(PriceHistory)
admin.site.register(SearchLog)
admin.site.register(LoginActivity)
admin.site.register(Wishlist)
admin.site.register(ResultCount)