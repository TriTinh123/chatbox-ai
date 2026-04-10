from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponse, StreamingHttpResponse
from django.utils.html import escape as esc_html
import json
from django.core.cache import cache

# ── Input limits ──────────────────────────────────────────────────────────
MAX_MESSAGE_LEN  = 4000   # characters per chat message
MAX_UPLOAD_MB    = 20     # MB per upload request


def _rate_limit(request, key: str, max_calls: int = 20, period: int = 60) -> bool:
    """
    Simple IP-based rate limiter using Django cache.
    Returns True when the request should be blocked.
    Works with any CACHE backend (LocMem in dev, Redis in prod).
    """
    ip = (
        request.META.get('HTTP_X_FORWARDED_FOR', '')
        .split(',')[0].strip()
        or request.META.get('REMOTE_ADDR', '0')
    )
    cache_key = f'rl:{key}:{ip}'
    count = cache.get(cache_key, 0)
    if count >= max_calls:
        return True
    cache.set(cache_key, count + 1, period)
    return False
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
from .services.gemini_fallback import ask_gemini, ask_gemini_stream, GeminiRateLimitError


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
            html=f'<div>{esc_html(user_text)}</div>'
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
            logger.exception('send_message error: %s', e)
            error_msg = Message.objects.create(
                chat_session=chat_session,
                role='assistant',
                text='Đã xảy ra lỗi, vui lòng thử lại.',
                html='<div style="color:#f87171">Đã xảy ra lỗi, vui lòng thử lại.</div>'
            )
            return Response({
                'error': 'Internal server error',
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
            logger.exception('_handle_intent error: %s', e)
            return '<div style="color:#f87171">Đã xảy ra lỗi khi xử lý yêu cầu, vui lòng thử lại.</div>'
    
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
    # Rate-limit: max 10 uploads/min per IP
    if _rate_limit(request, 'upload', max_calls=10, period=60):
        return JsonResponse({'error': 'Tải lên quá nhiều lần. Vui lòng thử lại sau 1 phút.'}, status=429)

    # File size guard
    content_length = request.META.get('CONTENT_LENGTH', 0)
    try:
        if int(content_length) > MAX_UPLOAD_MB * 1024 * 1024:
            return JsonResponse({'error': f'File quá lớn. Tối đa {MAX_UPLOAD_MB} MB.'}, status=413)
    except (ValueError, TypeError):
        pass

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
        logger.exception('upload_file error: %s', e)
        return JsonResponse({'error': 'Lỗi xử lý file. Vui lòng kiểm tra định dạng dữ liệu và thử lại.'}, status=500)


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

        elif chart_type == 'compare':
            p1 = request.GET.get('p1', '')
            p2 = request.GET.get('p2', '')
            if not p1 or not p2:
                return JsonResponse({'error': 'Thiếu tham số p1, p2 (YYYY-MM)'}, status=400)
            import pandas as _pd
            df2 = df.copy()
            df2['period'] = df2['date'].dt.to_period('M').astype(str)
            d1 = df2[df2['period'] == p1]
            d2 = df2[df2['period'] == p2]
            if d1.empty and d2.empty:
                return JsonResponse({'error': f'Không tìm thấy dữ liệu cho {p1} hoặc {p2}'}, status=404)
            return JsonResponse({
                'type': 'compare',
                'p1_label': p1, 'p2_label': p2,
                'p1_revenue': int(d1['revenue'].sum()), 'p2_revenue': int(d2['revenue'].sum()),
                'p1_quantity': int(d1['quantity'].sum()), 'p2_quantity': int(d2['quantity'].sum()),
            })

        else:
            return JsonResponse({'error': 'Unknown chart type'}, status=400)

    except Exception as e:
        logger.exception('chart_data_view error: %s', e)
        return JsonResponse({'error': 'Lỗi tải dữ liệu biểu đồ.'}, status=500)


@csrf_exempt
@require_http_methods(['GET'])
def export_excel_view(request):
    """Export all SalesData as an Excel file."""
    import io
    try:
        if not SalesData.objects.exists():
            return JsonResponse({'error': 'Chưa có dữ liệu. Vui lòng tải file trước.'}, status=404)
        qs = SalesData.objects.all().values('date', 'product', 'channel', 'region', 'quantity', 'unit_price', 'revenue')
        df = pd.DataFrame(list(qs))
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Sales Data')
        buf.seek(0)
        response = HttpResponse(
            buf.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="revenue_report.xlsx"'
        return response
    except Exception as e:
        logger.exception('export_excel_view error: %s', e)
        return JsonResponse({'error': 'Lỗi xuất file Excel.'}, status=500)


# ══ STREAMING CHAT ENDPOINT ══
@csrf_exempt
@require_http_methods(['POST'])
def stream_chat_view(request):
    """Stream AI response via Server-Sent Events (text/event-stream)."""
    # Rate-limit: max 30 messages/min per IP
    if _rate_limit(request, 'stream', max_calls=30, period=60):
        def _rate_event():
            msg = '<div style="color:#f59e0b">⚠️ Bạn gửi quá nhiều tin nhắn. Vui lòng chờ 1 phút rồi thử lại.</div>'
            yield f'data: {json.dumps(msg)}\n\n'
            yield 'data: [DONE]\n\n'
        r = StreamingHttpResponse(_rate_event(), content_type='text/event-stream; charset=utf-8')
        r['Cache-Control'] = 'no-cache'
        return r

    try:
        body = json.loads(request.body)
        user_text = body.get('text', '').strip()[:MAX_MESSAGE_LEN]
        session_key = body.get('session_key', 'default')[:64]  # cap session key length
    except Exception:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not user_text:
        return JsonResponse({'error': 'Empty message'}, status=400)

    # Get or create anonymous session
    session_title = f'{session_key} - Anonymous'
    chat_session = ChatSession.objects.filter(
        user__isnull=True, title=session_title
    ).first()
    if not chat_session:
        chat_session = ChatSession.objects.create(user=None, title=session_title)

    # Save user message
    Message.objects.create(
        chat_session=chat_session,
        role='user',
        text=user_text,
        html=f'<div>{esc_html(user_text)}</div>'
    )

    # Build conversation history (exclude the message just saved)
    all_msgs = list(Message.objects.filter(
        chat_session=chat_session
    ).order_by('created_at'))
    conversation_history = [
        {'role': m.role, 'text': m.text} for m in all_msgs[:-1]
    ]

    # Build data context
    if SalesData.objects.exists():
        sales_qs = SalesData.objects.all().values(
            'date', 'product', 'channel', 'region', 'quantity', 'unit_price', 'revenue'
        )
        df = pd.DataFrame(list(sales_qs))
        df['date'] = pd.to_datetime(df['date'])
        analyzer = DataAnalyzer(df=df)
        data_context = analyzer.recommendation()
        data_context.update(analyzer.breakdown_detailed())
        data_context.update(analyzer.advanced_analysis())
    else:
        data_context = {}

    chat_session_id = chat_session.id
    user_text_snap = user_text

    def event_stream():
        full_chunks = []
        try:
            for chunk in ask_gemini_stream(user_text_snap, data_context, conversation_history):
                full_chunks.append(chunk)
                yield f"data: {json.dumps(chunk)}\n\n"
        except GeminiRateLimitError:
            err_chunk = '<div style="color:#f59e0b">\u23f3 Gemini \u0111ang b\u1eadn, vui l\u00f2ng th\u1eed l\u1ea1i sau 20 gi\u00e2y.</div>'
            full_chunks.append(err_chunk)
            yield f"data: {json.dumps(err_chunk)}\n\n"
        except Exception as exc:
            logger.exception('stream_chat_view error: %s', exc)
            err_chunk = '<div style="color:#f28b82">Đã xảy ra lỗi, vui lòng thử lại.</div>'
            full_chunks.append(err_chunk)
            yield f"data: {json.dumps(err_chunk)}\n\n"
        finally:
            bot_html = ''.join(full_chunks)
            if bot_html:
                try:
                    cs = ChatSession.objects.get(id=chat_session_id)
                    Message.objects.create(
                        chat_session=cs,
                        role='assistant',
                        text=bot_html,
                        html=bot_html
                    )
                    if Message.objects.filter(chat_session=cs, role='user').count() == 1:
                        title = user_text_snap[:50] if len(user_text_snap) <= 52 else user_text_snap[:49] + '...'
                        cs.title = title
                        cs.save()
                except Exception:
                    pass
            yield "data: [DONE]\n\n"

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream; charset=utf-8')
    response['Cache-Control'] = 'no-cache, no-store'
    response['X-Accel-Buffering'] = 'no'
    return response


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
        logger.exception('summary_view error: %s', e)
        return JsonResponse({'error': 'Lỗi tải dữ liệu tóm tắt.'}, status=500)

