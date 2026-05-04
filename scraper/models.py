from django.db import models
from django.utils.text import slugify
from django.contrib.auth.models import User


class Product(models.Model):
    title      = models.CharField(max_length=255)
    slug       = models.SlugField(max_length=255, unique=True, blank=True)
    brand      = models.CharField(max_length=120, blank=True, null=True)
    image_url  = models.URLField(max_length=800, blank=True, null=True)
    category   = models.CharField(max_length=120, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)[:245]
            slug = base_slug
            counter = 1
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['-created_at']


class Offer(models.Model):
    STORE_CHOICES = [
        ('amazon',   'Amazon'),
        ('flipkart', 'Flipkart'),
        ('meesho',   'Meesho'),
        ('myntra',   'Myntra'),
    ]
    product    = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='offer_set')
    store      = models.CharField(max_length=50, choices=STORE_CHOICES)
    price      = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    url        = models.URLField(max_length=800, blank=True, null=True)
    rating     = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    review_cnt = models.IntegerField(null=True, blank=True)
    discount = models.CharField(max_length=500, blank=True, null=True)
    in_stock   = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('product', 'store')

    def __str__(self):
        return f"{self.store} — {self.product.title} — ₹{self.price}"


class PriceHistory(models.Model):
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name='history')
    price = models.DecimalField(max_digits=12, decimal_places=2)
    ts    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-ts']

    def __str__(self):
        return f"{self.offer} @ ₹{self.price} on {self.ts:%Y-%m-%d}"


class SearchLog(models.Model):
    query      = models.CharField(max_length=300)
    user       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    ts         = models.DateTimeField(auto_now_add=True)
    result_cnt = models.IntegerField(default=0)

    class Meta:
        ordering = ['-ts']

    def __str__(self):
        return f"{self.query} ({self.ts:%Y-%m-%d})"


class LoginActivity(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='login_activity')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, null=True)
    ts         = models.DateTimeField(auto_now_add=True)
    success    = models.BooleanField(default=True)

    class Meta:
        ordering = ['-ts']

    def __str__(self):
        return f"{self.user.username} — {'OK' if self.success else 'FAIL'} — {self.ts:%Y-%m-%d %H:%M}"


class ResultCount(models.Model):
    search_log = models.OneToOneField(SearchLog, on_delete=models.CASCADE)
    amazon     = models.IntegerField(default=0)
    flipkart   = models.IntegerField(default=0)
    meesho     = models.IntegerField(default=0)
    myntra     = models.IntegerField(default=0)

    def __str__(self):
        return f"Results for: {self.search_log.query}"


class Wishlist(models.Model):
    user          = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wishlist')
    product       = models.ForeignKey(Product, on_delete=models.CASCADE)
    added_at      = models.DateTimeField(auto_now_add=True)
    alert_on_drop = models.BooleanField(default=False)
    target_price  = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    email_alert   = models.EmailField(blank=True, null=True)

    class Meta:
        unique_together = ('user', 'product')

    def __str__(self):
        return f"{self.user.username} → {self.product.title}"


class Cart(models.Model):
    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name='cart')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Cart — {self.user.username}"

    def total(self):
        return sum(item.subtotal() for item in self.items.all())


class CartItem(models.Model):
    cart     = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    offer    = models.ForeignKey(Offer, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    def subtotal(self):
        return (self.offer.price or 0) * self.quantity

    def __str__(self):
        return f"{self.cart.user.username} — {self.offer.product.title}"


class Order(models.Model):
    STATUS_CHOICES = [
        ('pending',   'Pending'),
        ('confirmed', 'Confirmed'),
        ('shipped',   'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes       = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.pk} — {self.user.username} — {self.status}"


class OrderItem(models.Model):
    order       = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product     = models.ForeignKey(Product, on_delete=models.CASCADE)
    store       = models.CharField(max_length=50)
    store_url   = models.URLField(max_length=800, blank=True, null=True)
    price       = models.DecimalField(max_digits=12, decimal_places=2)
    quantity    = models.PositiveIntegerField(default=1)

    def subtotal(self):
        return self.price * self.quantity

    def __str__(self):
        return f"{self.product.title} x{self.quantity} — ₹{self.price}"