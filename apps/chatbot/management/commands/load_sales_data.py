"""
Django management command to load sales data from CSV file into database.
Usage: python manage.py load_sales_data /path/to/sales.csv
"""
from django.core.management.base import BaseCommand, CommandError
import pandas as pd
from apps.chatbot.models import SalesData


class Command(BaseCommand):
    help = 'Load sales data from CSV file into the database'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'csv_path',
            type=str,
            help='Path to the CSV file containing sales data'
        )
    
    def handle(self, *args, **options):
        csv_path = options['csv_path']
        
        try:
            # Load CSV
            df = pd.read_csv(csv_path, parse_dates=['date'])
            self.stdout.write(f"Loaded CSV: {csv_path} ({len(df)} rows)")
            
            # Clear existing data (optional)
            SalesData.objects.all().delete()
            self.stdout.write("Cleared existing SalesData")
            
            # Bulk create
            sales_data = [
                SalesData(
                    date=row['date'],
                    product=row['product'],
                    channel=row['channel'],
                    region=row['region'],
                    quantity=int(row['quantity']),
                    unit_price=int(row['unit_price']),
                    revenue=int(row['revenue'])
                )
                for _, row in df.iterrows()
            ]
            
            SalesData.objects.bulk_create(sales_data, batch_size=1000)
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully loaded {len(sales_data)} records into database'
                )
            )
        
        except FileNotFoundError:
            raise CommandError(f"CSV file not found: {csv_path}")
        except Exception as e:
            raise CommandError(f"Error loading CSV: {str(e)}")
