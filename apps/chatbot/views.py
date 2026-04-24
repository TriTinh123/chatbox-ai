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
import os
from google import genai
from google.genai import types

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
    build_quantity_or_price, build_worst_region, build_top_products
)
from .services.recommendations import build_recommendation
from .services.gemini_fallback import ask_gemini, ask_gemini_stream, ask_groq, ask_groq_general, ask_groq_stream, ask_groq_stream_general, GeminiRateLimitError, GroqRateLimitError
from .services.prompt_template import build_system_prompt, build_data_context, build_user_prompt, detect_language


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
        
        # Auto-detect language from user's message
        language = detect_language(user_text)
        
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
            
            # Detect language from user's message
            language = detect_language(user_text)
            
            # Route to appropriate handler based on intent
            if intent == 'greeting':
                # Handle greeting separately - don't need data analysis
                response_html = build_greeting(language)
            else:
                # Route to analysis handler
                response_html = self._handle_intent(intent, analyzer, user_text, chat_session, language)
            
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
    
    def _handle_intent(self, intent, analyzer, user_text, chat_session, language='vi'):
        """
        Route intent to Groq with COMPREHENSIVE analysis data.
        Sends ALL detailed breakdowns to ensure specific, data-driven responses.
        """
        try:
            # Language already detected, skip re-detection
            logger.info(f"[LANG] Using language: {language}")
            
            # ════════════════════════════════════════════════════════════════
            # STEP 1: Calculate COMPREHENSIVE analysis from sales.csv
            # ════════════════════════════════════════════════════════════════
            overview = analyzer.get_sales_summary()
            quantity_price = analyzer.quantity_or_price()
            worst_products = analyzer.worst_product()
            worst_channels = analyzer.worst_channel()
            worst_regions = analyzer.worst_region()
            breakdown = analyzer.breakdown_detailed()
            
            # Format analysis data in language-specific format
            if language == 'vi':
                analysis_text = f"""
DOANH THU TỪ sales.csv:
- Tháng này: {overview['current_revenue']:,.0f} đồng
- Tháng trước: {overview['previous_revenue']:,.0f} đồng
- Thay đổi: {overview['revenue_change_pct']:+.1f}%
- Số lượng thay đổi: {overview['quantity_change_pct']:+.1f}%
- Giá thay đổi: {overview['price_change_pct']:+.1f}%

NGUYÊN NHÂN: {quantity_price['dominant'].upper()}
- Số lượng: {quantity_price['qty_chg']:+.1f}%
- Giá: {quantity_price['price_chg']:+.1f}%

TOP SẢN PHẨM GIẢM:
"""
                for i, prod in enumerate(worst_products[:3], 1):
                    analysis_text += f"{i}. {prod['product']}: {prod['chg_pct']:+.1f}%\n"
                
                analysis_text += "\nTOP KÊNH GIẢM:\n"
                for i, ch in enumerate(worst_channels[:3], 1):
                    analysis_text += f"{i}. {ch['channel']}: {ch['chg_pct']:+.1f}%\n"
                
                analysis_text += "\nIMPACT (% tổng loss):\n"
                for prod in breakdown['product_breakdown'][:3]:
                    analysis_text += f"- {prod['product']}: {prod['impact_pct']:.1f}%\n"
                for ch in breakdown['channel_breakdown'][:3]:
                    analysis_text += f"- {ch['channel']}: {ch['impact_pct']:.1f}%\n"
            else:  # English
                analysis_text = f"""
REVENUE FROM sales.csv:
- This month: {overview['current_revenue']:,.0f}
- Previous month: {overview['previous_revenue']:,.0f}
- Change: {overview['revenue_change_pct']:+.1f}%
- Quantity change: {overview['quantity_change_pct']:+.1f}%
- Price change: {overview['price_change_pct']:+.1f}%

ROOT CAUSE: {quantity_price['dominant'].upper()}
- Quantity: {quantity_price['qty_chg']:+.1f}%
- Price: {quantity_price['price_chg']:+.1f}%

TOP DECLINING PRODUCTS:
"""
                for i, prod in enumerate(worst_products[:3], 1):
                    analysis_text += f"{i}. {prod['product']}: {prod['chg_pct']:+.1f}%\n"
                
                analysis_text += "\nTOP DECLINING CHANNELS:\n"
                for i, ch in enumerate(worst_channels[:3], 1):
                    analysis_text += f"{i}. {ch['channel']}: {ch['chg_pct']:+.1f}%\n"
                
                analysis_text += "\nIMPACT (% of total loss):\n"
                for prod in breakdown['product_breakdown'][:3]:
                    analysis_text += f"- {prod['product']}: {prod['impact_pct']:.1f}%\n"
                for ch in breakdown['channel_breakdown'][:3]:
                    analysis_text += f"- {ch['channel']}: {ch['impact_pct']:.1f}%\n"
            
            # ════════════════════════════════════════════════════════════════
            # STEP 2: Get chat history for context
            # ════════════════════════════════════════════════════════════════
            chat_messages = Message.objects.filter(
                chat_session=chat_session
            ).order_by('-created_at')[:6]  # Last 6 messages for better context
            
            chat_history_text = ""
            for msg in reversed(list(chat_messages)):
                role = "User" if msg.role == 'user' else "Bot"
                # Clean HTML from previous responses
                text = msg.text.replace('<div>', '').replace('</div>', '').replace('<br>', '').strip()[:150]
                chat_history_text += f"{role}: {text}\n"
            
            if not chat_history_text.strip():
                chat_history_text = "(Đây là tin nhắn đầu tiên)"
            
            # ════════════════════════════════════════════════════════════════
            # STEP 3: Build comprehensive prompt (language-aware)
            # ════════════════════════════════════════════════════════════════
            if language == 'vi':
                full_prompt = f"""Dữ liệu phân tích:
{analysis_text}

Câu hỏi: {user_text}

CẤU TRÚC TRẢ LỜI (BẮT BUỘC - phải có đúng 5 dòng này):
NHẬN ĐỊNH: [Nguyên nhân chính, số %]
YẾU TỐ QUAN TRỌNG: [Sản phẩm/kênh, số %]
ẢNH HƯỞNG: [% tổng loss]
HÀNH ĐỘNG: Thứ nhất: [Hành động]. Thứ hai: [Hành động].
RỦI RO: Nếu không hành động: [Hậu quả]"""
            else:  # English
                full_prompt = f"""Analysis data:
{analysis_text}

Question: {user_text}

RESPONSE STRUCTURE (MANDATORY - must have exactly these 5 lines):
INSIGHT: [Main reason, percentage]
CRITICAL FACTOR: [Product/Channel, percentage]
IMPACT: [Percentage of total loss]
ACTIONS: First: [Action]. Second: [Action].
RISK: If no action: [Consequence]"""
            
            # ════════════════════════════════════════════════════════════════
            # STEP 4: Call Groq with language-aware system prompt
            # ════════════════════════════════════════════════════════════════
            system_prompt = build_system_prompt(language)
            
            try:
                from groq import Groq
                import os
                
                groq_key = os.getenv('GROQ_API_KEY')
                if not groq_key:
                    raise ValueError("GROQ_API_KEY not set in .env")
                
                client = Groq(api_key=groq_key)
                
                logger.info(f"[GROQ] Calling Groq API with llama-3.1-8b-instant")
                logger.info(f"[GROQ] Prompt length: {len(full_prompt)} chars, Data section length: {len(analysis_text)} chars")
                
                groq_response = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        # Few-shot Vietnamese example - natural style
                        {"role": "user", "content": "Tại sao doanh thu giảm?"},
                        {"role": "assistant", "content": """Doanh thu tháng 3 giảm 81.2% từ 74.48 tỷ xuống 13.99 tỷ đồng. Nguyên nhân chính là số lượng bán giảm 76%, trong khi giá chỉ giảm 2%. Điều này cho thấy vấn đề là lực bán yếu đi chứ không phải giá.

Sản phẩm gặp khó nhất là Laptop (-87.5%) và kênh bán Offline (-84.5%). Hai yếu tố này chiếm khoảng 70% tổng sụt giảm, nên nên ưu tiên phục hồi. Cụ thể, Laptop chiếm 28% tổng loss và Offline chiếm 26.2%.

Cần thực hiện ngay: Thứ nhất, tập trung phục hồi Laptop vì đây là yếu tố có impact cao nhất. Thứ hai, rà soát lại chiến lược kênh Offline để tìm ra nguyên nhân sụt giảm."""},
                        # Few-shot English example - natural style
                        {"role": "user", "content": "Why is revenue decreasing?"},
                        {"role": "assistant", "content": """Revenue dropped 81.2% from 74.48B to 13.99B. The main reason is that sales quantity fell 76% while price only decreased 2% - this shows the issue is low sales volume, not pricing.

The biggest impact comes from Laptop (-87.5%) and Offline channel (-84.5%), which account for about 70% of the total loss. Laptop alone represents 28% of the loss and Offline channel 26.2%.

My recommendation: First, focus on recovering Laptop sales since it has the highest impact. Second, review your Offline channel strategy to understand why it's declining so sharply. Without action, revenue will continue falling as you lose ground in your key products and channels."""},
                        # Real user question
                        {"role": "user", "content": full_prompt}
                    ],
                    temperature=0.3,  # Slightly higher for variety while staying data-driven
                    max_tokens=1024
                )
                
                bot_response = groq_response.choices[0].message.content
                logger.info(f"[GROQ] Response received: {len(bot_response)} chars")
                logger.info(f"[GROQ] First 200 chars: {bot_response[:200]}")
                
            except (GroqRateLimitError, ValueError) as e:
                logger.warning(f"[GROQ] Failed: {str(e)}, trying Gemini fallback...")
                try:
                    bot_response = ask_gemini(user_text, overview, [], language=language)
                    logger.info(f"[GEMINI] Fallback succeeded")
                except Exception as e2:
                    logger.exception(f"[ERROR] Both Groq and Gemini failed: {str(e2)}")
                    bot_response = 'Lỗi: Không thể kết nối với dịch vụ AI. Vui lòng thử lại sau.'
            except Exception as e:
                logger.exception(f"[ERROR] Unexpected error: {str(e)}")
                bot_response = f'Lỗi: {str(e)[:100]}'
            
            return bot_response
        
        except Exception as e:
            logger.exception('_handle_intent error: %s', e)
            return 'Đã xảy ra lỗi khi xử lý yêu cầu, vui lòng thử lại.'
    
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
    
    def _handle_intent(self, intent, analyzer, user_text, chat_session, language='vi'):
        """
        Route intent to Groq with analysis data.
        Simpler version for PublicChatViewSet.
        """
        try:
            # Language already detected, skip re-detection
            logger.info(f"[LANG] Using language: {language}")
            
            # Get basic analysis for context
            overview = analyzer.get_sales_summary()
            
            # Get chat history
            chat_messages = Message.objects.filter(
                chat_session=chat_session
            ).order_by('-created_at')[:6]
            
            # Format chat history
            chat_history_text = ""
            for msg in reversed(list(chat_messages)):
                role = "User" if msg.role == 'user' else "Bot"
                text = msg.text.replace('<div>', '').replace('</div>', '').replace('<br>', '').strip()[:150]
                chat_history_text += f"{role}: {text}\n"
            
            if not chat_history_text.strip():
                chat_history_text = "(First message)" if language == 'en' else "(Đây là tin nhắn đầu tiên)"
            
            # Build analysis summary for prompt
            analysis_summary = f"""Current Revenue: {overview.get('current_revenue', 'N/A')}
Change: {overview.get('revenue_change_pct', 'N/A')}%
Current Month: {overview.get('current_month', 'N/A')}"""
            
            # Build prompt with language awareness
            if language == 'en':
                full_prompt = f"""Conversation context:
{chat_history_text}

Question:
{user_text}

Sales data:
{analysis_summary}

Requirements:
- Answer directly in English
- Use specific numbers
- Be concise and clear
"""
            else:  # Vietnamese
                full_prompt = f"""Ngữ cảnh hội thoại:
{chat_history_text}

Câu hỏi:
{user_text}

Dữ liệu doanh thu:
{analysis_summary}

Yêu cầu:
- Trả lời bằng tiếng Việt
- Dùng số cụ thể
- Trả lời ngắn gọn và rõ ràng
"""
            
            system_prompt = build_system_prompt(language)
            
            try:
                from groq import Groq
                import os
                
                groq_key = os.getenv('GROQ_API_KEY')
                if not groq_key:
                    raise ValueError("GROQ_API_KEY not set in .env")
                
                client = Groq(api_key=groq_key)
                
                groq_response = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        # Few-shot examples to teach the model the expected style (NATURAL, NO EMOJI LABELS)
                        {"role": "user", "content": "Doanh thu tháng này có giảm không?"},
                        {"role": "assistant", "content": "Doanh thu tháng 3 giảm 81.2% từ 74.48 tỷ xuống 13.99 tỷ đồng. Mức sụt giảm này chủ yếu do số lượng bán giảm 76%, trong khi giá chỉ giảm 2%, nên nguyên nhân chính là lực bán yếu đi. Đáng chú ý, Laptop giảm 87.5% và Offline giảm 84.5% - hai yếu tố này chiếm 70% mức sụt, cho thấy vấn đề tập trung vào sản phẩm và kênh cụ thể. Nên ưu tiên phục hồi Laptop vì impact cao nhất. Nếu không hành động, doanh thu sẽ tiếp tục giảm."},
                        {"role": "user", "content": "Vì sao?"},
                        {"role": "assistant", "content": "Nguyên nhân chính là số lượng bán ra giảm mạnh, không phải do giá. Cụ thể, Laptop (-87.5%) và kênh Offline (-84.5%) là hai yếu tố đóng góp lớn nhất vào mức giảm tổng. Điều này cho thấy sự sụt giảm tập trung ở sản phẩm và kênh này. Dữ liệu hiện tại chưa đủ để xác định nguyên nhân sâu hơn."},
                        {"role": "user", "content": "Nên làm gì?"},
                        {"role": "assistant", "content": "Nên ưu tiên phục hồi Laptop và rà soát lại kênh Offline vì đây là hai điểm kéo doanh thu xuống mạnh nhất. Cần tập trung cải thiện hiệu quả bán ở hai khu vực này trước. Nếu không xử lý, doanh thu sẽ khó phục hồi trong ngắn hạn."},
                        # Real user question
                        {"role": "user", "content": full_prompt}
                    ],
                    temperature=0.15,
                    max_tokens=2048
                )
                
                bot_response = groq_response.choices[0].message.content
                
            except (GroqRateLimitError, ValueError) as e:
                try:
                    bot_response = ask_gemini(user_text, overview, [], language=language)
                except Exception as e2:
                    bot_response = 'Lỗi: Không thể kết nối với dịch vụ AI. Vui lòng thử lại sau.'
            except Exception as e:
                bot_response = f'Lỗi: {str(e)[:100]}'
            
            return bot_response
        
        except Exception as e:
            logger.exception('_handle_intent error: %s', e)
            return 'Đã xảy ra lỗi khi xử lý yêu cầu, vui lòng thử lại.'
    
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
            
            # Auto-detect language from user's message
            language = detect_language(user_text)

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
                # No sales data → pure Groq conversation (natural like real Gemini)
                try:
                    bot_html = ask_groq(user_text, {}, conversation_history, language=language)
                except (GroqRateLimitError, ValueError):
                    # Fallback to Gemini
                    try:
                        bot_html = ask_gemini(user_text, {}, conversation_history)
                    except Exception:
                        bot_html = '<div>Xin chào! Tôi là trợ lý phân tích doanh thu. Hãy upload file CSV để bắt đầu phân tích.</div>'
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
                
                logger.info(f"[PUBLIC DEBUG] User text: '{user_text}' | Detected intent: '{intent}' | Conversation history length: {len(conversation_history)}")
                print(f"\n{'='*80}")
                print(f"[PUBLIC DEBUG] User: {user_text}")
                print(f"[PUBLIC DEBUG] Intent: {intent}")
                print(f"[PUBLIC DEBUG] Has history: {len(conversation_history) > 0}")
                print(f"{'='*80}\n")

                # Greeting lần đầu (chưa có lịch sử) → template nhanh
                if intent == 'greeting' and not conversation_history:
                    logger.info(f"[PUBLIC] Detected GREETING, returning quick greeting template")
                    print(f"[PUBLIC] → Using build_greeting()")
                    bot_html = build_greeting(language)
                # Greeting với history hoặc non-data questions → pure Groq conversation
                elif intent == 'greeting' or intent == 'default':
                    logger.info(f"[PUBLIC] Detected {intent}, using pure Groq general conversation")
                    print(f"[PUBLIC] → Using ask_groq_general() for natural conversation")
                    try:
                        bot_html = ask_groq_general(user_text, conversation_history, language=language)
                        logger.info(f"[PUBLIC] Groq general succeeded")
                    except (GroqRateLimitError, ValueError) as e:
                        logger.warning(f"[PUBLIC] Groq general failed ({type(e).__name__}), trying Gemini")
                        print(f"[PUBLIC] Groq error: {str(e)[:100]}")
                        try:
                            bot_html = ask_gemini(user_text, {}, conversation_history, language=language)
                            logger.info(f"[PUBLIC] Gemini succeeded")
                        except Exception as e2:
                            logger.error(f"[PUBLIC] Gemini also failed: {str(e2)[:100]}")
                            bot_html = '<div>Xin lỗi, tôi đang bận. Vui lòng thử lại sau.</div>'
                    except Exception as e:
                        logger.error(f"[PUBLIC] ask_groq_general error: {str(e)[:150]}")
                        print(f"[PUBLIC] Exception: {str(e)[:100]}")
                        bot_html = f'<div>Xin lỗi, đã có lỗi xảy ra. Vui lòng thử lại.</div>'
                else:
                    # All revenue/data questions → use _handle_intent with full analysis
                    logger.info(f"[PUBLIC] Detected {intent}, calling _handle_intent with full analysis")
                    print(f"[PUBLIC] → Using _handle_intent()")
                    bot_html = self._handle_intent(intent, analyzer, user_text, chat_session, language)

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

            objects = []
            for idx, (_, row) in enumerate(df.iterrows()):
                try:
                    obj = SalesData(
                        date=row['date'].date(),
                        source_file=file.name,
                        product=str(row['product']).strip() if pd.notna(row['product']) else '',
                        channel=str(row['channel']).strip() if pd.notna(row['channel']) else '',
                        region=str(row['region']).strip() if pd.notna(row['region']) else '',
                        quantity=int(float(row['quantity'])) if pd.notna(row['quantity']) else 0,
                        unit_price=int(float(row['unit_price'])) if pd.notna(row['unit_price']) else 0,
                        revenue=int(float(row['revenue'])) if pd.notna(row['revenue']) else 0,
                    )
                    objects.append(obj)
                except Exception as row_err:
                    return JsonResponse({
                        'error': f'Lỗi dòng {idx+1}: {str(row_err)}'
                    }, status=400)
            all_objects.extend(objects)
            file_summaries.append({
                'name': file.name,
                'rows': len(objects),
                'cols': len(df.columns),
                'info': f'{len(objects)} dòng · {len(df.columns)} cột',
            })

        with transaction.atomic():
            # Delete old data and insert new
            SalesData.objects.all().delete()
            SalesData.objects.bulk_create(all_objects, batch_size=500)

        return JsonResponse({
            'status': 'success',
            'files': file_summaries,
            # backward-compat single-file fields
            'filename': file_summaries[0]['name'] if file_summaries else '',
            'rows': len(all_objects),
            'cols': file_summaries[0]['cols'] if file_summaries else 0,
        })

    except Exception as e:
        import traceback
        logger.error('upload_file error: %s\n%s', str(e), traceback.format_exc())
        return JsonResponse({'error': f'Lỗi: {str(e)}'}, status=500)


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

        elif chart_type == 'top_products':
            latest_month = df['date'].dt.to_period('M').max()
            top_products = (
                df[df['date'].dt.to_period('M') == latest_month]
                .groupby('product')['revenue']
                .sum()
                .sort_values(ascending=False)
                .head(3)
            )
            return JsonResponse({
                'type': 'top_products',
                'month': str(latest_month),
                'labels': top_products.index.tolist(),
                'data': [int(v) for v in top_products.values],
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
        # Auto-detect language from user's message
        detected_language = detect_language(user_text)
        language = body.get('language', detected_language)  # Allow client override, but detect if not provided
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

    # Build data context - if data exists in DB
    if SalesData.objects.exists():
        sales_qs = SalesData.objects.all().values(
            'date', 'product', 'channel', 'region', 'quantity', 'unit_price', 'revenue'
        )
        df = pd.DataFrame(list(sales_qs))
        df['date'] = pd.to_datetime(df['date'])
        analyzer = DataAnalyzer(df=df)
        
        # Get sales summary with 16 fields
        summary = analyzer.get_sales_summary()
        
        # Convert to data_context format for ask_groq_stream
        data_context = {
            'cur_month': summary.get('current_month'),
            'prev_month': summary.get('previous_month'),
            'cur_rev': summary.get('current_revenue'),
            'prev_rev': summary.get('previous_revenue'),
            'chg_pct': summary.get('revenue_change_pct'),
            'cur_qty': summary.get('current_quantity'),
            'prev_qty': summary.get('previous_quantity'),
            'qty_chg_pct': summary.get('quantity_change_pct'),
            'cur_price': summary.get('current_avg_price'),
            'prev_price': summary.get('previous_avg_price'),
            'price_chg_pct': summary.get('price_change_pct'),
            'dominant': summary.get('dominant_factor'),
            'worst_product': summary.get('worst_product_name'),
            'prod_chg': summary.get('worst_product_change_pct'),
            'worst_channel': summary.get('worst_channel_name'),
            'ch_chg': summary.get('worst_channel_change_pct'),
        }
        logger.info(f"[STREAM] Data context: {data_context}")
        print(f"\n[STREAM DEBUG] Data context has {len(data_context)} fields")
        print(f"[STREAM DEBUG] Revenue change: {data_context.get('chg_pct')}%\n")
    else:
        data_context = {}
        logger.warning("[STREAM] No sales data in DB!")

    chat_session_id = chat_session.id
    user_text_snap = user_text

    # ✅ STREAM: Detect intent for routing (like in PublicChatViewSet)
    last_message = Message.objects.filter(
        chat_session=chat_session, role='assistant'
    ).order_by('-created_at').first()
    last_intent = getattr(last_message, '_detected_intent', None) if last_message else None
    intent = detect_intent(user_text_snap, last_intent)
    
    print(f"\n[STREAM DEBUG] User: {user_text_snap}")
    print(f"[STREAM DEBUG] Intent: {intent}")
    print(f"[STREAM DEBUG] Using ask_groq_stream or ask_groq_stream_general...\n")

    def event_stream():
        full_chunks = []
        try:
            # ✅ Route based on intent
            if intent == 'greeting' and not conversation_history:
                # First-time greeting → use template with emojis
                print(f"[STREAM] → GREETING (first message), using build_greeting() template")
                greeting_html = build_greeting(language)
                yield f"data: {json.dumps(greeting_html)}\n\n"
                full_chunks.append(greeting_html)
            elif intent == 'default' or intent == 'greeting':
                # General question or subsequent greeting - NO revenue data needed
                print(f"[STREAM] → Using ask_groq_stream_general() for natural conversation")
                for chunk in ask_groq_stream_general(user_text_snap, conversation_history, language=language):
                    full_chunks.append(chunk)
                    yield f"data: {json.dumps(chunk)}\n\n"
            else:
                # Revenue/data question - use full analysis
                print(f"[STREAM] → {intent} intent detected, calling ask_groq_stream with data")
                for chunk in ask_groq_stream(user_text_snap, data_context, conversation_history, language=language):
                    full_chunks.append(chunk)
                    yield f"data: {json.dumps(chunk)}\n\n"
        except GeminiRateLimitError:
            # ✅ IMPROVED: Use enhanced fallback response instead of error
            # This makes the chatbot work perfectly without Gemini!
            from .services.gemini_fallback import generate_fallback_response
            fallback_chunk = generate_fallback_response(data_context, user_text_snap, conversation_history)
            full_chunks.append(fallback_chunk)
            yield f"data: {json.dumps(fallback_chunk)}\n\n"
        except Exception as exc:
            logger.exception('stream_chat_view error: %s', exc)
            # Use fallback for any error
            from .services.gemini_fallback import generate_fallback_response
            fallback_chunk = generate_fallback_response(data_context, user_text_snap, conversation_history)
            full_chunks.append(fallback_chunk)
            yield f"data: {json.dumps(fallback_chunk)}\n\n"
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

