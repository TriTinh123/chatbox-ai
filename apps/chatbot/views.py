from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.db import models, transaction
import pandas as pd
import traceback
import logging

logger = logging.getLogger(__name__)

from .models import ChatSession, Message, SalesData, FileAttachment
from .serializers import (
    ChatSessionSerializer, ChatSessionDetailSerializer, MessageSerializer, 
    MessageCreateSerializer
)
from .services.chatbot_logic import detect_intent, QUICK_REPLIES
from .services.analysis import DataAnalyzer
from .services.forecasting import RevenueForecaster
from .services.insights import (
    build_greeting, build_overview_revenue, build_worst_product, build_worst_channel,
    build_quantity_or_price, build_worst_region
)
from .services.recommendations import build_recommendation
from .services.gemini_fallback import ask_gemini, GeminiRateLimitError


class ChatSessionViewSet(viewsets.ModelViewSet):
    """API for chat sessions: list, create, retrieve, update, delete."""
    permission_classes = [permissions.AllowAny]
    serializer_class = ChatSessionSerializer
    parser_classes = (MultiPartParser, FormParser)
    
    def get_queryset(self):
        """Return all sessions."""
        return ChatSession.objects.all()
    
    def perform_create(self, serializer):
        """Create session without user."""
        serializer.save()
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ChatSessionDetailSerializer
        return ChatSessionSerializer
    
    @action(detail=True, methods=['post'])
    def send_message(self, request, pk=None):
        """Process user message and return bot response."""
        try:
            chat_session = self.get_object()
        except ChatSession.DoesNotExist:
            return Response({'error': 'Chat not found'}, status=status.HTTP_404_NOT_FOUND)
        
        user_text = request.data.get('text', '').strip()
        if not user_text:
            return Response({'error': 'Empty message'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Save user message
        user_message = Message.objects.create(
            chat_session=chat_session,
            role='user',
            text=user_text,
            html=f'<div>{user_text}</div>'
        )
        
        # Load sales data
        try:
            if not SalesData.objects.exists():
                return Response(
                    {'error': 'No sales data loaded. Please upload CSV first.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Build analyzer from DB
            sales_qs = SalesData.objects.all().values(
                'date', 'product', 'channel', 'region', 'quantity', 'unit_price', 'revenue'
            )
            df = pd.DataFrame(list(sales_qs))
            
            if df.empty:
                return Response(
                    {'error': 'Sales data is empty'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            df['date'] = pd.to_datetime(df['date'])
            analyzer = DataAnalyzer(df=df)
            
            # Detect intent from user message
            last_message = Message.objects.filter(
                chat_session=chat_session, role='assistant'
            ).order_by('-created_at').first()
            last_intent = getattr(last_message, '_detected_intent', None) if last_message else None
            
            intent = detect_intent(user_text, last_intent)
            
            # Route to appropriate analysis
            response_html = self._handle_intent(intent, analyzer, user_text)
            
            # Save bot response
            bot_message = Message.objects.create(
                chat_session=chat_session,
                role='assistant',
                text=response_html,
                html=response_html
            )
            bot_message._detected_intent = intent
            bot_message.save()
            
            # Update chat title if first message
            if Message.objects.filter(chat_session=chat_session, role='user').count() == 1:
                title = user_text[:50] if len(user_text) <= 52 else user_text[:49] + '...'
                chat_session.title = title
                chat_session.save()
            
            # Get suggested quick replies
            quick_replies = QUICK_REPLIES.get(intent, QUICK_REPLIES['default'])
            
            return Response({
                'user_message': MessageSerializer(user_message).data,
                'bot_message': MessageSerializer(bot_message).data,
                'quick_replies': quick_replies
            }, status=status.HTTP_201_CREATED)
        
        except GeminiRateLimitError:
            error_msg = Message.objects.create(
                chat_session=chat_session,
                role='assistant',
                text='Gemini API rate limited. Try again later.',
                html='<div style="color:#f87171">Gemini API rate limited. Try again later.</div>'
            )
            return Response({
                'error': 'Rate limit exceeded',
                'bot_message': MessageSerializer(error_msg).data
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)
        
        except Exception as e:
            error_msg = Message.objects.create(
                chat_session=chat_session,
                role='assistant',
                text=f'Error: {str(e)}',
                html=f'<div style="color:#f87171">Error: {str(e)}</div>'
            )
            return Response({
                'error': str(e),
                'bot_message': MessageSerializer(error_msg).data
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _handle_intent(self, intent, analyzer, user_text):
        """Route intent to appropriate analysis function."""
        try:
            # Simple greeting - quick response
            if intent == 'greeting':
                return build_greeting()
            
            # Detailed analysis always uses Gemini for natural explanation
            elif intent == 'detailed_analysis':
                data_context = analyzer.recommendation()
                breakdown = analyzer.breakdown_detailed()
                advanced = analyzer.advanced_analysis()
                data_context.update(breakdown)
                data_context.update(advanced)
                return ask_gemini(user_text, data_context)
            
            elif intent == 'overview_revenue':
                data = analyzer.overview_revenue()
                return build_overview_revenue(data)
            
            elif intent == 'worst_product':
                data = analyzer.worst_product()
                return build_worst_product(data)
            
            elif intent == 'worst_channel':
                data = analyzer.worst_channel()
                return build_worst_channel(data)
            
            elif intent == 'quantity_or_price':
                data = analyzer.quantity_or_price()
                return build_quantity_or_price(data)
            
            elif intent == 'worst_region':
                data = analyzer.worst_region()
                return build_worst_region(data)
            
            elif intent == 'forecast':
                forecaster = RevenueForecaster(df=analyzer.df)
                forecast_data = forecaster.predict_next()
                # TODO: Build forecast HTML response
                return f'<div class="tag">📈 Dự báo doanh thu</div><pre>{forecast_data}</pre>'
            
            elif intent == 'recommendation':
                rec_data = analyzer.recommendation()
                return build_recommendation(rec_data)
            
            else:
                # Default: fallback to Gemini for open-ended questions
                data_context = analyzer.recommendation()
                # Thêm breakdown chi tiết để Gemini phân tích
                breakdown = analyzer.breakdown_detailed()
                data_context.update(breakdown)
                return ask_gemini(user_text, data_context)
        
        except Exception as e:
            return f'<div style="color:#f87171">Lỗi: {str(e)}</div>'
    
    @action(detail=True, methods=['post'])
    def rename(self, request, pk=None):
        """Rename chat session."""
        try:
            chat = self.get_object()
            chat.title = request.data.get('title', chat.title)
            chat.save()
            return Response({'message': 'Renamed successfully'})
        except ChatSession.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=True, methods=['post'])
    def pin_toggle(self, request, pk=None):
        """Toggle pin status."""
        try:
            chat = self.get_object()
            chat.pinned = not chat.pinned
            chat.save()
            return Response({'pinned': chat.pinned})
        except ChatSession.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=True, methods=['post'])
    def upload_file(self, request, pk=None):
        """Upload and parse CSV file."""
        try:
            chat = self.get_object()
            file = request.FILES.get('file')
            
            if not file:
                return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Parse CSV
            df = pd.read_csv(file)
            rows, cols = df.shape
            
            # Save attachment record
            attachment = FileAttachment.objects.create(
                chat_session=chat,
                file=file,
                filename=file.name,
                rows_count=rows,
                cols_count=cols
            )
            
            return Response({
                'message': f'Uploaded {rows} rows × {cols} columns',
                'attachment': {
                    'filename': file.name,
                    'rows': rows,
                    'cols': cols
                }
            })
        
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)



def health_check_view(request):
    """Health check endpoint."""
    return JsonResponse({'status': 'ok'})


class PublicChatViewSet(viewsets.ViewSet):
    """Public chatbot API - No authentication required."""
    permission_classes = [permissions.AllowAny]
    
    def dispatch(self, request, *args, **kwargs):
        """Exempt from CSRF for API."""
        return super().dispatch(request, *args, **kwargs)
    
    dispatch = csrf_exempt(dispatch)
    
    def list(self, request):
        """List public chats (placeholder)."""
        return Response({'message': 'Use send-message action to chat'})
    
    @action(detail=False, methods=['post'], url_path='send-message')
    def send_message(self, request):
        """Process user message - Allow anonymous users."""
        user_text = ''
        session_key = request.data.get('session_key', 'default')

        try:
            user_text = request.data.get('text', '').strip()

            if not user_text:
                return Response({'error': 'Empty message'}, status=status.HTTP_400_BAD_REQUEST)

            # Get or create session — exact match by session_key
            # Title format: "<session_key> - Anonymous"
            session_title = f'{session_key} - Anonymous'
            chat_session = ChatSession.objects.filter(
                user__isnull=True,
                title=session_title
            ).first()
            if not chat_session:
                chat_session = ChatSession.objects.create(
                    user=None,
                    title=session_title
                )

            # Save user message
            Message.objects.create(
                chat_session=chat_session,
                role='user',
                text=user_text,
                html=f'<div>{user_text}</div>'
            )

            # ── Fetch toàn bộ lịch sử hội thoại (ngoại trừ tin hiện tại vừa lưu) ──
            all_msgs = list(Message.objects.filter(
                chat_session=chat_session
            ).order_by('created_at'))
            # all_msgs[-1] là tin user vừa lưu → loại ra, Gemini nhận qua user_message
            conversation_history = [
                {'role': m.role, 'text': m.text}
                for m in all_msgs[:-1]
            ]

            # ── Full pipeline ──────────────────────────
            if not SalesData.objects.exists():
                # No sales data → pure Gemini conversation (natural like real Gemini)
                try:
                    bot_html = ask_gemini(user_text, {}, conversation_history)
                except Exception:
                    bot_html = '<div>Xin chào! Tôi là trợ lý phân tích doanh thu. Hãy upload file CSV để bắt đầu phân tích.</div>'
            else:
                # Build DataFrame
                sales_qs = SalesData.objects.all().values(
                    'date', 'product', 'channel', 'region', 'quantity', 'unit_price', 'revenue'
                )
                df = pd.DataFrame(list(sales_qs))
                df['date'] = pd.to_datetime(df['date'])
                analyzer = DataAnalyzer(df=df)

                # Detect intent
                last_message = Message.objects.filter(
                    chat_session=chat_session, role='assistant'
                ).order_by('-created_at').first()
                last_intent = getattr(last_message, '_detected_intent', None) if last_message else None
                intent = detect_intent(user_text, last_intent)

                # Greeting lần đầu (chưa có lịch sử) → template nhanh
                # Greeting giữa hội thoại → Gemini nhớ ngữ cảnh và trả lời tự nhiên
                if intent == 'greeting' and not conversation_history:
                    bot_html = build_greeting()
                else:
                    # TẤT CẢ câu hỏi → Gemini với TOÀN BỘ lịch sử hội thoại
                    data_context = analyzer.recommendation()
                    breakdown = analyzer.breakdown_detailed()
                    advanced = analyzer.advanced_analysis()
                    data_context.update(breakdown)
                    data_context.update(advanced)
                    try:
                        bot_html = ask_gemini(user_text, data_context, conversation_history)
                    except Exception as e:
                        bot_html = f'<div style="color:#f87171">Lỗi: {str(e)[:100]}</div>'

            # Save bot response
            bot_msg = Message.objects.create(
                chat_session=chat_session,
                role='assistant',
                text=bot_html,
                html=bot_html
            )

            return Response({
                'status': 'success',
                'user_message': user_text,
                'bot_response': bot_html,
                'session_id': chat_session.id,
                'session_key': session_key
            }, status=status.HTTP_200_OK)

        except GeminiRateLimitError:
            retry_html = '<div style="color:#f59e0b">⏳ Gemini đang bận, vui lòng thử lại sau 20 giây.</div>'
            return Response({
                'status': 'success',
                'user_message': user_text,
                'bot_response': retry_html,
                'session_id': 0,
                'session_key': session_key
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error("PublicChatViewSet.send_message error:\n%s", traceback.format_exc())
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ══ FILE UPLOAD ENDPOINT ══
@csrf_exempt
@require_http_methods(['POST'])
def upload_file(request):
    """Upload and process one or more data files for sales analysis."""
    try:
        files = request.FILES.getlist('files')
        if not files:
            # fallback: single-file key
            f = request.FILES.get('file')
            if f:
                files = [f]
            else:
                return JsonResponse({'error': 'No file provided'}, status=400)

        required_cols = {'date', 'product', 'channel', 'region', 'quantity', 'unit_price', 'revenue'}
        all_objects = []
        file_summaries = []

        for file in files:
            if not file.name.lower().endswith(('.csv', '.xlsx', '.xls')):
                return JsonResponse({'error': f'File không hợp lệ: {file.name}. Chỉ hỗ trợ .csv, .xlsx, .xls'}, status=400)

            try:
                if file.name.lower().endswith('.csv'):
                    df = pd.read_csv(file)
                else:
                    df = pd.read_excel(file)
            except Exception as e:
                return JsonResponse({'error': f'Lỗi đọc file {file.name}: {str(e)}'}, status=400)

            df_cols_lower = {col.lower() for col in df.columns}
            if not required_cols.issubset(df_cols_lower):
                missing = required_cols - df_cols_lower
                return JsonResponse({'error': f'File {file.name} thiếu cột: {", ".join(missing)}'}, status=400)

            df.columns = [c.lower() for c in df.columns]
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df = df.dropna(subset=['date'])

            objects = [
                SalesData(
                    date=row['date'].date(),
                    source_file=file.name,
                    product=str(row.get('product', '')),
                    channel=str(row.get('channel', '')),
                    region=str(row.get('region', '')),
                    quantity=int(float(row.get('quantity', 0))),
                    unit_price=int(float(row.get('unit_price', 0))),
                    revenue=int(float(row.get('revenue', 0))),
                )
                for _, row in df.iterrows()
            ]
            all_objects.extend(objects)
            file_summaries.append({
                'name': file.name,
                'rows': len(objects),
                'cols': len(df.columns),
                'info': f'{len(objects)} dòng · {len(df.columns)} cột',
            })

        with transaction.atomic():
            SalesData.objects.all().delete()
            SalesData.objects.bulk_create(all_objects, batch_size=500)

        return JsonResponse({
            'status': 'success',
            'files': file_summaries,
            # backward-compat single-file fields
            'filename': file_summaries[0]['name'],
            'rows': len(all_objects),
            'cols': file_summaries[0]['cols'],
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ══ CHART DATA ENDPOINT ══
@csrf_exempt
def chart_data_view(request):
    """Return aggregated sales data for Chart.js visualizations."""
    try:
        if not SalesData.objects.exists():
            return JsonResponse({'error': 'Chưa có dữ liệu. Hãy upload file CSV trước.'}, status=404)

        sales_qs = SalesData.objects.all().values(
            'date', 'product', 'channel', 'region', 'quantity', 'unit_price', 'revenue'
        )
        df = pd.DataFrame(list(sales_qs))
        df['date'] = pd.to_datetime(df['date'])

        chart_type = request.GET.get('type', 'overview')

        if chart_type == 'overview':
            monthly = df.groupby(df['date'].dt.to_period('M'))['revenue'].sum().sort_index()
            return JsonResponse({
                'type': 'overview',
                'labels': [str(p) for p in monthly.index],
                'data': [int(v) for v in monthly.values],
            })

        elif chart_type == 'product':
            by_product = df.groupby('product')['revenue'].sum().sort_values(ascending=True)
            return JsonResponse({
                'type': 'product',
                'labels': by_product.index.tolist(),
                'data': [int(v) for v in by_product.values],
            })

        elif chart_type == 'region':
            by_region = df.groupby('region')['revenue'].sum().sort_values(ascending=False)
            return JsonResponse({
                'type': 'region',
                'labels': by_region.index.tolist(),
                'data': [int(v) for v in by_region.values],
            })

        elif chart_type == 'decline':
            monthly_rev = df.groupby(df['date'].dt.to_period('M'))['revenue'].sum().sort_index()
            monthly_qty = df.groupby(df['date'].dt.to_period('M'))['quantity'].sum().sort_index()
            return JsonResponse({
                'type': 'decline',
                'labels': [str(p) for p in monthly_rev.index],
                'revenue': [int(v) for v in monthly_rev.values],
                'quantity': [int(v) for v in monthly_qty.values],
            })

        elif chart_type == 'forecast':
            import numpy as np
            monthly = df.groupby(df['date'].dt.to_period('M'))['revenue'].sum().sort_index()
            x = np.arange(len(monthly))
            y = monthly.values.astype(float)
            coeffs = np.polyfit(x, y, 1)
            forecast_x = np.arange(len(monthly), len(monthly) + 3)
            forecast_y = np.polyval(coeffs, forecast_x)
            last_period = monthly.index[-1]
            future_labels = [str(last_period + i) for i in range(1, 4)]
            return JsonResponse({
                'type': 'forecast',
                'labels': [str(p) for p in monthly.index],
                'actual': [int(v) for v in y],
                'forecast_labels': future_labels,
                'forecast': [max(0, int(v)) for v in forecast_y],
            })

        else:
            return JsonResponse({'error': 'Unknown chart type'}, status=400)

    except Exception as e:
        logger.error("chart_data_view error:\n%s", traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


def summary_view(request):
    """Return quick KPI strip for the dashboard summary bar."""
    try:
        if not SalesData.objects.exists():
            return JsonResponse({'has_data': False})

        qs = SalesData.objects.all().values('date', 'product', 'channel', 'region', 'revenue')
        df = pd.DataFrame(list(qs))
        if df.empty:
            return JsonResponse({'has_data': False})

        df['date'] = pd.to_datetime(df['date'])
        df['revenue'] = pd.to_numeric(df['revenue'], errors='coerce').fillna(0.0)
        df['product'] = df['product'].fillna('N/A').astype(str)
        df['channel'] = df['channel'].fillna('N/A').astype(str)
        df['region'] = df['region'].fillna('N/A').astype(str)

        # Month-over-month revenue change
        monthly = df.groupby(df['date'].dt.to_period('M'))['revenue'].sum().sort_index()
        current_month_revenue = float(monthly.iloc[-1]) if len(monthly) >= 1 else 0.0
        previous_month_revenue = float(monthly.iloc[-2]) if len(monthly) >= 2 else 0.0
        rev_change_amount = current_month_revenue - previous_month_revenue
        if len(monthly) >= 2 and previous_month_revenue != 0:
            rev_change = round((rev_change_amount / previous_month_revenue) * 100, 1)
        else:
            rev_change = 0.0

        current_month_label = monthly.index[-1].strftime('%m/%Y') if len(monthly) >= 1 else 'N/A'
        previous_month_label = monthly.index[-2].strftime('%m/%Y') if len(monthly) >= 2 else 'N/A'

        by_product = df.groupby('product')['revenue'].sum()
        worst_product = str(by_product.idxmin()) if len(by_product) > 0 else 'N/A'
        best_product  = str(by_product.idxmax()) if len(by_product) > 0 else 'N/A'
        best_product_revenue = float(by_product.max()) if len(by_product) > 0 else 0.0
        worst_product_revenue = float(by_product.min()) if len(by_product) > 0 else 0.0

        by_channel = df.groupby('channel')['revenue'].sum()
        worst_channel = str(by_channel.idxmin()) if len(by_channel) > 0 else 'N/A'
        best_channel  = str(by_channel.idxmax()) if len(by_channel) > 0 else 'N/A'
        best_channel_revenue = float(by_channel.max()) if len(by_channel) > 0 else 0.0
        worst_channel_revenue = float(by_channel.min()) if len(by_channel) > 0 else 0.0

        by_region = df.groupby('region')['revenue'].sum()
        best_region = str(by_region.idxmax()) if len(by_region) > 0 else 'N/A'
        worst_region = str(by_region.idxmin()) if len(by_region) > 0 else 'N/A'
        best_region_revenue = float(by_region.max()) if len(by_region) > 0 else 0.0
        worst_region_revenue = float(by_region.min()) if len(by_region) > 0 else 0.0

        total_rev = int(df['revenue'].sum())
        total_rows = len(df)
        avg_order_value = int(round(total_rev / total_rows, 0)) if total_rows > 0 else 0

        def share_pct(value):
            return round((value / total_rev) * 100, 1) if total_rev > 0 else 0.0

        return JsonResponse({
            'has_data': True,
            'total_revenue': total_rev,
            'total_rows': total_rows,
            'avg_order_value': avg_order_value,

            'current_month_label': current_month_label,
            'previous_month_label': previous_month_label,
            'current_month_revenue': int(round(current_month_revenue)),
            'previous_month_revenue': int(round(previous_month_revenue)),

            'rev_change': rev_change,
            'rev_change_amount': int(round(rev_change_amount)),

            'worst_product': worst_product,
            'best_product': best_product,
            'best_product_revenue': int(round(best_product_revenue)),
            'worst_product_revenue': int(round(worst_product_revenue)),
            'best_product_share_pct': share_pct(best_product_revenue),
            'worst_product_share_pct': share_pct(worst_product_revenue),

            'worst_channel': worst_channel,
            'best_channel': best_channel,
            'best_channel_revenue': int(round(best_channel_revenue)),
            'worst_channel_revenue': int(round(worst_channel_revenue)),
            'best_channel_share_pct': share_pct(best_channel_revenue),
            'worst_channel_share_pct': share_pct(worst_channel_revenue),

            'best_region': best_region,
            'worst_region': worst_region,
            'best_region_revenue': int(round(best_region_revenue)),
            'worst_region_revenue': int(round(worst_region_revenue)),
            'best_region_share_pct': share_pct(best_region_revenue),
            'worst_region_share_pct': share_pct(worst_region_revenue),
        })
    except Exception as e:
        logger.error("summary_view error:\n%s", traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)

