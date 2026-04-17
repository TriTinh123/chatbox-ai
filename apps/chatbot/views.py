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
from .services.prompt_template import build_system_prompt, build_data_context, build_user_prompt


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
            
            # Route to appropriate analysis with chat_session for history
            response_html = self._handle_intent(intent, analyzer, user_text, chat_session)
            
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
    
    def _handle_intent(self, intent, analyzer, user_text, chat_session):
        """
        Route intent to Groq with COMPREHENSIVE analysis data.
        Sends ALL detailed breakdowns to ensure specific, data-driven responses.
        """
        try:
            # ════════════════════════════════════════════════════════════════
            # STEP 1: Calculate COMPREHENSIVE analysis from sales.csv
            # ════════════════════════════════════════════════════════════════
            overview = analyzer.get_sales_summary()
            quantity_price = analyzer.quantity_or_price()
            worst_products = analyzer.worst_product()
            worst_channels = analyzer.worst_channel()
            worst_regions = analyzer.worst_region()
            breakdown = analyzer.breakdown_detailed()
            
            # Format all detailed analysis data
            analysis_text = f"""
╔════════════════════════════════════════════════════════════════════════════════╗
║ DỮ LIỆU BÁN HÀNG TỪ sales.csv - KHÔNG TÍNH TOÁN LẠI, CHỈ DÙNG SỐ NÀY
╚════════════════════════════════════════════════════════════════════════════════╝

📊 KỲ SO SÁNH: {overview['current_month']} so với {overview['previous_month']}

╔════════════════════════════════════════════════════════════════════════════════╗
║ 1. TỔNG QUAN DOANH THU & SỐ LƯỢNG
╚════════════════════════════════════════════════════════════════════════════════╝
💰 DOANH THU:
- Tháng này ({overview['current_month']}): {overview['current_revenue']:,.0f} đồng
- Tháng trước ({overview['previous_month']}): {overview['previous_revenue']:,.0f} đồng
- Thay đổi: {overview['revenue_change_pct']:+.1f}% (số tiền: {int(overview['current_revenue'] - overview['previous_revenue']):+,} đồng)

📦 SỐ LƯỢNG BÁN:
- Tháng này: {overview['current_quantity']:,} sản phẩm
- Tháng trước: {overview['previous_quantity']:,} sản phẩm
- Thay đổi: {overview['quantity_change_pct']:+.1f}%

💵 GIÁ BÌNH QUÂN/SP:
- Tháng này: {overview['current_avg_price']:,.2f} đồng/sp
- Tháng trước: {overview['previous_avg_price']:,.2f} đồng/sp
- Thay đổi: {overview['price_change_pct']:+.1f}%

╔════════════════════════════════════════════════════════════════════════════════╗
║ 2. NGUYÊN NHÂN THAY ĐỔI DOANH THU
╚════════════════════════════════════════════════════════════════════════════════╝
🎯 YẾU TỐ CHIẾU DIỄM: {quantity_price['dominant'].upper()}
- Nếu SỐ LƯỢNG giảm: {quantity_price['qty_chg']:+.1f}% (nguyên nhân chính)
- Nếu GIÁ giảm: {quantity_price['price_chg']:+.1f}% (nguyên nhân chính)

╔════════════════════════════════════════════════════════════════════════════════╗
║ 3. SẢN PHẨM BỊ TỪ TỪ GIẢM (Từ xấu nhất đến tốt nhất)
╚════════════════════════════════════════════════════════════════════════════════╝
"""
            for i, prod in enumerate(worst_products[:5], 1):
                analysis_text += f"{i}. {prod['product']}: {prod['chg_pct']:+.1f}% (từ {prod['prev_rev']} → {prod['cur_rev']})\n"
            
            analysis_text += f"""
╔════════════════════════════════════════════════════════════════════════════════╗
║ 4. KÊNH BÁN HƯ (Từ xấu nhất đến tốt nhất)
╚════════════════════════════════════════════════════════════════════════════════╝
"""
            for i, ch in enumerate(worst_channels[:5], 1):
                analysis_text += f"{i}. {ch['channel']}: {ch['chg_pct']:+.1f}% (từ {ch['prev_rev']} → {ch['cur_rev']})\n"
            
            analysis_text += f"""
╔════════════════════════════════════════════════════════════════════════════════╗
║ 5. KHU VỰC BỊ ẢNH HƯỞNG (Từ xấu nhất đến tốt nhất)
╚════════════════════════════════════════════════════════════════════════════════╝
"""
            for i, reg in enumerate(worst_regions[:5], 1):
                analysis_text += f"{i}. {reg['region']}: {reg['chg_pct']:+.1f}% (từ {reg['cur_rev']} → Doanh thu hiện tại)\n"
            
            analysis_text += f"""
╔════════════════════════════════════════════════════════════════════════════════╗
║ 6. PHÂN TÍCH IMPACT: CÁC YẾU TỐ GÓP PHẦN VÀO SỤT GIẢM DOANH THU
╚════════════════════════════════════════════════════════════════════════════════╝

🔴 SẢN PHẨM GIẢM (Tính % tổng loss):
"""
            for prod in breakdown['product_breakdown'][:5]:
                analysis_text += f"- {prod['product']}: {prod['chg_pct']:+.1f}% change, góp {prod['impact_pct']:.1f}% vào sụt giảm\n"
            
            analysis_text += f"""
🔴 KÊNH BÁN GIẢM (Tính % tổng loss):
"""
            for ch in breakdown['channel_breakdown'][:5]:
                analysis_text += f"- {ch['channel']}: {ch['chg_pct']:+.1f}% change, góp {ch['impact_pct']:.1f}% vào sụt giảm\n"
            
            analysis_text += f"""
🔴 KHU VỰC GIẢM (Tính % tổng loss):
"""
            for reg in breakdown['region_breakdown'][:5]:
                analysis_text += f"- {reg['region']}: {reg['chg_pct']:+.1f}% change, góp {reg['impact_pct']:.1f}% vào sụt giảm\n"
            
            analysis_text += """
╔════════════════════════════════════════════════════════════════════════════════╗
║ [HẾT DỮ LIỆU] - KHÔNG CÓ DỮ LIỆU KHÁC, CHỈ DÙNG DỮ LIỆU TRÊN ĐỂ TRẢ LỜI
╚════════════════════════════════════════════════════════════════════════════════╝
"""
            
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
            # STEP 3: Build comprehensive prompt
            # ════════════════════════════════════════════════════════════════
            full_prompt = f"""Ngữ cảnh hội thoại:
{chat_history_text}

Câu hỏi:
{user_text}

Dữ liệu phân tích:
{analysis_text}

Yêu cầu:
- Trả lời bằng tiếng Việt
- Trả lời trực tiếp
- Không chào lại
- Không nói chung chung
- Phải có số liệu
- Phải giải thích rõ nguyên nhân
- Hiểu câu hỏi ngắn theo ngữ cảnh

Yêu cầu bổ sung:
- Trả lời đầy đủ, có chiều sâu
- Không trả lời quá ngắn
- Phải có giải thích + insight
"""
            
            # Debug logging
            logger.info(f"[GROQ] Intent detected: {intent}")
            logger.info(f"[GROQ] User question: {user_text}")
            
            # ════════════════════════════════════════════════════════════════
            # STEP 4: Call Groq with EXTREMELY strict system prompt
            # ════════════════════════════════════════════════════════════════
            system_prompt = """You are Revenue AI, a senior Vietnamese business analyst.

Your job is to explain sales and revenue changes in a natural, insightful, and human-like way.

CORE RULES:
- Answer directly, no unnecessary greeting
- Do not use vague phrases like "có thể", "thường là"
- Do not give generic theory
- Only use provided analysis data
- Always include numbers when available
- If data is missing, say: "Không đủ dữ liệu để kết luận chính xác."
- CRITICAL: Do NOT guess reasons like marketing, competition, staff, external factors
- ONLY explain based on available data (quantity, price, product, channel)
- Do NOT suggest possible causes beyond the data (no marketing, tồn kho, sales, trưng bày)
- If deeper causes are unknown, clearly say: "Dữ liệu hiện tại chưa đủ để xác định nguyên nhân sâu hơn."

🚨 NO GUESSING RULE (CỰC QUAN TRỌNG):
- NEVER suggest causes like tồn kho, trưng bày, marketing, nhân viên
- Only describe what is visible in the data
- If deeper cause is unknown, say:
  "Dữ liệu hiện tại chưa đủ để xác định nguyên nhân sâu hơn."
- NEVER guess reasons like:
  ❌ "có thể do marketing kém"
  ❌ "có thể do nhân viên"
  ❌ "có thể do tồn kho"
  ❌ "có thể do cạnh tranh"
  ❌ "có thể do nhu cầu khách"
- Only explain based on ACTUAL DATA:
  ✅ Quantity change %
  ✅ Price change %
  ✅ Product-specific data
  ✅ Channel-specific data
- If the real cause is NOT in data, say: "Dữ liệu hiện tại chưa đủ để xác định nguyên nhân sâu hơn."
- NEVER assume causes beyond the provided metrics

RECOMMENDATIONS (HÀNH ĐỘNG):
- Recommendations must be high-level only, no specific actions like marketing, quảng cáo, trưng bày, nhân viên
- NEVER mention specific actions like marketing, quảng cáo, trải nghiệm, nhân viên under any condition
- Focus only on product or channel performance from data

STYLE:
- Natural Vietnamese
- Calm, confident
- Like a real business analyst
- Not robotic, not textbook
- Do not repeat the same point multiple times
- Mention each key factor only once
- Keep answers concise and sharp

DEPTH REQUIREMENT (QUAN TRỌNG):
- Do NOT be too short
- Expand answers with deeper explanation
- Always include 1–2 extra layers:
  + explain WHY it happens
  + explain business impact
- Answers should feel complete, not minimal
- PRIORITY: Depth > Brevity (longer detailed answer is better than short vague answer)

DEPTH IS MANDATORY (QUAN TRỌNG CẤP ĐỘ CAO):
- For "Vì sao?" questions: MUST explain 2-3 layers minimum
  + What changed (the fact)
  + Why it changed (root cause from data)
  + What it means (impact on business)
- Do NOT answer "Vì sao?" in 1-2 sentences
- Add extra insight about products/channels/numbers involved
- Expand with: "Điều này cho thấy..." or "Cụ thể là..." to add depth
- Always include specific percentages and product/channel names

FLEXIBLE 5-PART STRUCTURE (INTERNALLY - NOT ALWAYS LABELING):
Use this 5-part framework INTERNALLY to organize thoughts, but express naturally like human conversation:

1️⃣ CONCLUSION (Kết luận chính)
   - Lead with direct answer to user's question
   - Include specific numbers/percentages
   - No need to label explicitly - integrate naturally into opening

2️⃣ CAUSE (Nguyên nhân chính)
   - Explain WHY based on data (quantity, price, product, channel)
   - Use phrases like "Cụ thể là...", "Điều này là do..." 
   - Do NOT label or use emoji headers

3️⃣ INSIGHT (Insight quan trọng - the differentiator)
   - Show deeper pattern recognition
   - Use "Đáng chú ý...", "Điều này cho thấy..."
   - Connect cause to business impact naturally

4️⃣ ACTION (Nên làm gì - if relevant)
   - For "What to do?" questions, suggest prioritized actions
   - Format: "Thứ nhất..., thứ hai..." (no need to label)
   - Link each action to its consequence

5️⃣ CONSEQUENCE (Hậu quả - always at the end)
   - State what happens if NOT acted upon
   - Natural close: "Nếu không..., sẽ..."
   - DO NOT use emoji labels

Few-shot examples (SHOW ALL 5 PARTS):

EXAMPLE 1 - Revenue decline
User: "Doanh thu tháng này có giảm không?"
Assistant: "🟢 KẾT LUẬN: Doanh thu tháng 3 giảm 81.2% từ 74.48 tỷ xuống 13.99 tỷ. 🔵 NGUYÊN NHÂN: Số lượng giảm 76% (gây 80% sụt), giá giảm 2% (gây 20% sụt). 🔵 INSIGHT: Laptop -87.5% & Offline -84.5% chiếm 70% sụt → vấn đề tập trung ở sản phẩm & kênh. 🎯 HÀNH ĐỘNG: Ưu tiên phục hồi Laptop. ⚠️ HẬU QUẢ: Nếu không, doanh thu tiếp tục giảm."

EXAMPLE 2 - Root cause
User: "Vì sao?"
Assistant: "🟢 KẾT LUẬN: Sức bán yếu, không phải giá. 🔵 NGUYÊN NHÂN: Qty -76% vs Price -2% → vấn đề bán hàng. Laptop -87.5%, Offline -84.5%. 🔵 INSIGHT: Gợi ý tồn kho, trưng bày hoặc năng lực sales, không phải nhu cầu chung. 🎯 HÀNH ĐỘNG: Rà soát 2 điểm này. ⚠️ HẬU QUẢ: Nếu bỏ qua, doanh số tiếp tục sụt 10-20% tháng sau."

EXAMPLE 3 - Action  
User: "Nên làm gì?"
Assistant: "🟢 KẾT LUẬN: Tập trung phục hồi Laptop & Offline. 🔵 NGUYÊN NHÂN: 2 yếu tố này chiếm 70% sụt. 🔵 INSIGHT: Không nên giảm giá mà kiểm tra tồn kho, display, năng lực bán. 🎯 HÀNH ĐỘNG: (1) Kiểm tồn Laptop - thiếu→nhập, thừa→cải display; (2) Rà soát Offline - staff, khuyến mãi, năng lực. ⚠️ HẬU QUẢ: Nếu không, doanh thu giảm 10-20% tháng sau, mất cơ hội tăng trưởng."\""""

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
                    temperature=0.2,  # Low temperature for consistent, data-driven responses
                    max_tokens=2048
                )
                
                bot_response = groq_response.choices[0].message.content
                logger.info(f"[GROQ] Response received: {len(bot_response)} chars")
                logger.info(f"[GROQ] First 200 chars: {bot_response[:200]}")
                
            except (GroqRateLimitError, ValueError) as e:
                logger.warning(f"[GROQ] Failed: {str(e)}, trying Gemini fallback...")
                try:
                    bot_response = ask_gemini(user_text, overview, [])
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
    
    def _handle_intent(self, intent, analyzer, user_text, chat_session):
        """
        Route intent to Groq with COMPREHENSIVE analysis data.
        Sends ALL detailed breakdowns to ensure specific, data-driven responses.
        """
        try:
            # Calculate comprehensive analysis
            overview = analyzer.get_sales_summary()
            quantity_price = analyzer.quantity_or_price()
            worst_products = analyzer.worst_product()
            worst_channels = analyzer.worst_channel()
            worst_regions = analyzer.worst_region()
            breakdown = analyzer.breakdown_detailed()
            
            # Format optimized analysis data (COMPACT for API)
            analysis_text = f"""[SỰ THAY ĐỔI DOANH THU]
Kỳ so sánh: {overview['current_month']} vs {overview['previous_month']}
Doanh thu: {overview['current_revenue']:,.0f} đ ({overview['revenue_change_pct']:+.1f}%) - Số lượng: {overview['current_quantity']:,} ({overview['quantity_change_pct']:+.1f}%) - Giá: {overview['current_avg_price']:,.0f} ({overview['price_change_pct']:+.1f}%)

[NGUYÊN NHÂN]
Yếu tố chính: {quantity_price['dominant']} ({quantity_price['qty_chg']:+.1f}% số lượng, {quantity_price['price_chg']:+.1f}% giá)

[SẢN PHẨM GIẢM (Top 3)]
"""
            for prod in worst_products[:3]:
                analysis_text += f"- {prod['product']}: {prod['chg_pct']:+.1f}% (đóng góp {breakdown['product_breakdown'][0]['impact_pct'] if breakdown['product_breakdown'] else 0:.1f}%)\n"
            
            analysis_text += f"""
[KÊNH GIẢM (Top 3)]
"""
            for ch in worst_channels[:3]:
                analysis_text += f"- {ch['channel']}: {ch['chg_pct']:+.1f}%\n"
            
            analysis_text += """
[CHỈ DÙNG DỮ LIỆU TRÊN ĐỂ TRẢ LỜI - KHÔNG CÓ DỮ LIỆU KHÁC]"""
            
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
                chat_history_text = "(Đây là tin nhắn đầu tiên)"
            
            # Build comprehensive prompt
            full_prompt = f"""Ngữ cảnh hội thoại:
{chat_history_text}

Câu hỏi:
{user_text}

Dữ liệu phân tích:
{analysis_text}

Yêu cầu:
- Trả lời bằng tiếng Việt
- Trả lời trực tiếp
- Không chào lại
- Không nói chung chung
- Phải có số liệu
- Phải giải thích rõ nguyên nhân
- Hiểu câu hỏi ngắn theo ngữ cảnh

Yêu cầu bổ sung:
- Trả lời đầy đủ, có chiều sâu
- Không trả lời quá ngắn
- Phải có giải thích + insight
"""
            
            system_prompt = """You are Revenue AI, a senior Vietnamese business analyst.

Your job is to explain sales and revenue changes in a natural, insightful, and human-like way.

CORE RULES:
- Answer directly, no unnecessary greeting
- Do not use vague phrases like "có thể", "thường là"
- Do not give generic theory
- Only use provided analysis data
- Always include numbers when available
- If data is missing, say: "Không đủ dữ liệu để kết luận chính xác."
- CRITICAL: Do NOT guess reasons like marketing, competition, staff, external factors
- ONLY explain based on available data (quantity, price, product, channel)
- Do NOT suggest possible causes beyond the data (no marketing, tồn kho, sales, trưng bày)
- If deeper causes are unknown, clearly say: "Dữ liệu hiện tại chưa đủ để xác định nguyên nhân sâu hơn."

🚨 NO GUESSING RULE (CỰC QUAN TRỌNG):
- NEVER suggest causes like tồn kho, trưng bày, marketing, nhân viên
- Only describe what is visible in the data
- If deeper cause is unknown, say:
  "Dữ liệu hiện tại chưa đủ để xác định nguyên nhân sâu hơn."
- NEVER guess reasons like:
  ❌ "có thể do marketing kém"
  ❌ "có thể do nhân viên"
  ❌ "có thể do tồn kho"
  ❌ "có thể do cạnh tranh"
  ❌ "có thể do nhu cầu khách"
- Only explain based on ACTUAL DATA:
  ✅ Quantity change %
  ✅ Price change %
  ✅ Product-specific data
  ✅ Channel-specific data
- If the real cause is NOT in data, say: "Dữ liệu hiện tại chưa đủ để xác định nguyên nhân sâu hơn."
- NEVER assume causes beyond the provided metrics

RECOMMENDATIONS (HÀNH ĐỘNG):
- Recommendations must be high-level only, no specific actions like marketing, quảng cáo, trưng bày, nhân viên
- NEVER mention specific actions like marketing, quảng cáo, trải nghiệm, nhân viên under any condition
- Focus only on product or channel performance from data

STYLE:
- Natural Vietnamese
- Calm, confident
- Like a real business analyst
- Not robotic, not textbook
- Do not repeat the same idea
- Keep answers concise (3–5 sentences)
- Mention each key factor only once
- Do not repeat the same point multiple times
- Keep answers concise and sharp

DEPTH REQUIREMENT (QUAN TRỌNG):
- Do NOT be too short
- Expand answers with deeper explanation
- Always include 1–2 extra layers:
  + explain WHY it happens
  + explain business impact
- Answers should feel complete, not minimal
- PRIORITY: Depth > Brevity (longer detailed answer is better than short vague answer)

DEPTH IS MANDATORY (QUAN TRỌNG CẤP ĐỘ CAO):
- For "Vì sao?" questions: MUST explain 2-3 layers minimum
  + What changed (the fact)
  + Why it changed (root cause from data)
  + What it means (impact on business)
- Do NOT answer "Vì sao?" in 1-2 sentences
- Add extra insight about products/channels/numbers involved
- Expand with: "Điều này cho thấy..." or "Cụ thể là..." to add depth
- Always include specific percentages and product/channel names

MANDATORY 5-PART STRUCTURE (ALL RESPONSES MUST INCLUDE):
Follow this exact 5-part framework for EVERY analytical response:

🔥 1. KẾT LUẬN CHÍNH (Conclusion) - MANDATORY
   👉 Trả lời thẳng câu hỏi của user (YES/NO + kết quả)
   ✅ Examples:
   - "Doanh thu tháng 3 giảm 81.2% so với tháng trước"
   - "Laptop giảm 87.5%, là sản phẩm bị ảnh hưởng nặng nhất"
   ❗ Rules:
   - Luôn có CON SỐ (số % hoặc tiền)
   - Không vòng vo, thẳng thắn
   - Tối đa 1-2 câu

🟢 2. NGUYÊN NHÂN CHÍNH (Cause) - MANDATORY
   👉 Giải thích LÝ DO bằng DATA (không phỏng đoán)
   ✅ Example: "Số lượng bán giảm 76% (đóng góp 80%), giá chỉ giảm 2% (đóng góp 20%)"
   ❗ Rules:
   - Chỉ dùng data có sẵn (quantity, price, product, channel)
   - KHÔNG đoán về marketing, cạnh tranh, nhân viên
   - Nếu chưa rõ, nói "Dữ liệu chưa đủ để kết luận"
   - Include specific percentages từ data

🔵 3. INSIGHT QUAN TRỌNG (Deep Insight) - MANDATORY
   👉 Phần làm bạn "khác biệt" - cho thấy AI thực sự hiểu dữ liệu
   ✅ Examples:
   - "Laptop & Offline chiếm 70% mức sụt, không phải nhu cầu chung"
   - "Vấn đề tập trung ở sản phẩm cụ thể, gợi ý tồn kho hoặc trưng bày"
   ❗ Rules:
   - Liên kết nguyên nhân với tác động
   - So sánh các yếu tố
   - Business-focused

🎯 4. HÀNH ĐỘNG (Action) - MANDATORY (nếu relevant)
   👉 Nếu có "Nên làm gì?" → MUST INCLUDE action & consequence
   ✅ Example: "Phục hồi Laptop (87.5% giảm) → kiểm tra tồn kho & display"
   ❗ Rules:
   - Priority: cái nào impact cao → cái nào tiếp theo
   - Format: "Thứ nhất... (vì...). Thứ hai..."
   - Liên kết hành động với consequence

⚠️ 5. HẬU QUẢ (Impact/Consequence) - MANDATORY
   👉 RÕNG RÀO: sẽ xảy ra gì nếu không hành động
   ✅ Example: "Nếu không, doanh thu sẽ tiếp tục giảm 10-20%, ảnh hưởng KPI"
   ❗ Rules:
   - Luôn kết thúc bằng hậu quả NEGATIF rõ ràng
   - Tone: "gắt" nhưng không điều động
- "có thể do..." (FORBIDDEN - this is guessing, not data-based analysis)
- "thường là..." (FORBIDDEN - vague generalization)
- "có thể là..." (FORBIDDEN - pure speculation)

WRITING STYLE:
- For analytical/explanation questions: EXPAND answers with depth
- Do NOT keep responses minimal or brief
- For "Vì sao?" or "Tại sao?": Must explain 2-3 layers (WHAT changed → WHY it changed → IMPACT)
- Add 1-2 more sentences explaining deeper insight and business impact
- Aim for 4-7 sentences for complex analysis questions
- Length should match question complexity: simple question = brief, complex question = detailed
- Clear, sharp, meaningful language (not fluff, but substantive explanation)"""

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
                    bot_response = ask_gemini(user_text, overview, [])
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
                    bot_html = ask_groq(user_text, {}, conversation_history)
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
                    bot_html = build_greeting()
                elif intent == 'default' or (intent == 'greeting' and conversation_history):
                    # Default intent = question không liên quan đến data → pure Groq conversation (general)
                    # OR greeting with history = followup greeting → use natural response
                    logger.info(f"[PUBLIC] Detected {intent}, using pure Groq general conversation")
                    print(f"[PUBLIC] → Using ask_groq_general() for natural conversation")
                    try:
                        bot_html = ask_groq_general(user_text, conversation_history)
                        logger.info(f"[PUBLIC] Groq general succeeded")
                    except (GroqRateLimitError, ValueError) as e:
                        logger.warning(f"[PUBLIC] Groq general failed ({type(e).__name__}), trying Gemini")
                        print(f"[PUBLIC] Groq error: {str(e)[:100]}")
                        try:
                            bot_html = ask_gemini(user_text, {}, conversation_history)
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
                    bot_html = self._handle_intent(intent, analyzer, user_text, chat_session)

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
                greeting_html = build_greeting()
                yield f"data: {json.dumps(greeting_html)}\n\n"
                full_chunks.append(greeting_html)
            elif intent == 'default' or intent == 'greeting':
                # General question or subsequent greeting - NO revenue data needed
                print(f"[STREAM] → Using ask_groq_stream_general() for natural conversation")
                for chunk in ask_groq_stream_general(user_text_snap, conversation_history):
                    full_chunks.append(chunk)
                    yield f"data: {json.dumps(chunk)}\n\n"
            else:
                # Revenue/data question - use full analysis
                print(f"[STREAM] → {intent} intent detected, calling ask_groq_stream with data")
                for chunk in ask_groq_stream(user_text_snap, data_context, conversation_history):
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

