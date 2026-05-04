from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from scraper.models import Wishlist, Offer

class Command(BaseCommand):
    help = 'Send price drop alerts to users'

    def handle(self, *args, **kwargs):
        wishlist_items = Wishlist.objects.filter(
            alert_on_drop=True,
            target_price__isnull=False
        ).select_related('product', 'user')

        sent = 0
        for item in wishlist_items:
            best_offer = Offer.objects.filter(
                product=item.product
            ).order_by('price').first()

            if not best_offer or not best_offer.price:
                continue

            if best_offer.price <= item.target_price:
                email = item.email_alert or item.user.email
                if not email:
                    continue
                try:
                    send_mail(
                        subject=f'Price Drop Alert - {item.product.title[:50]}',
                        message=f'''
Hi {item.user.username}!

Great news! Price drop alert!

Product: {item.product.title}
Current Price: Rs.{best_offer.price}
Your Target:   Rs.{item.target_price}
Best Store:    {best_offer.store.capitalize()}
Buy Now:       {best_offer.url}

Happy Shopping!
- PriceMatchX Team
                        ''',
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[email],
                        fail_silently=False,
                    )
                    sent += 1
                    self.stdout.write(f'Alert sent to {email}')
                except Exception as e:
                    self.stdout.write(f'Failed: {e}')

        self.stdout.write(f'\nDone! {sent} alerts sent.')