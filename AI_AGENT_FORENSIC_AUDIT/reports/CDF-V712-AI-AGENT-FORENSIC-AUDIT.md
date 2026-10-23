# تقرير التدقيق الجنائي المستقل لوكلاء الذكاء الاصطناعي — CDF–GCO–CRMS v7.12

إدارة الحوكمة والامتثال المؤسسي — صندوق التنمية الثقافي · التاريخ: 2026-10-23 · تصنيف التدقيق: تأكيد تقني مستقل، قائم على التنفيذ، للقراءة فقط

## الخلاصة التنفيذية

**الحكم التقني:** DETERMINISTIC_AGENT_SIMULATION_ONLY — النظام لا يحتوي على أي تكامل مع مزوّد نماذج ذكاء اصطناعي، ولا يُجري أي استدعاء لنموذج. الفريق الأسود والمدافع والمحكّم ثلاث دوال بايثون بجداول قواعد ثابتة تعمل في عملية واحدة وخيط واحد على كائنات مشتركة؛ الفصل بينها فصل وظيفي وسجلّي لا فصل سياق أو تنفيذ. المحرك نفسه يصرّح بذلك في كل سجل (SINGLE_PROCESS_RULE_BASED). لا يوجد وكيل تحرير ولا قارئ مستقل للمادة 20 في الشفرة.

**جاهزية الاستخدام المؤسسي:** TECHNICAL_REMEDIATION_REQUIRED — الضوابط الحتمية قوية وصمدت أمام محاولات الالتفاف (لا اعتماد بشري مزوّر من قيمة منطقية أو سجل غير موقّع أو معدّل، لا عكس ذاتي لملاحظة صادرة، لا اعتماد عنوان دون سجل قرار، سلاسل التجزئة سليمة، فحص السرية نظيف). لكن فجوتين تمنعان حتى التجربة المحكومة لوظيفة التحدي: التحدي ليس على مسار الإصدار (يمكن بناء المصنف وملف Word بعد مراجعة أعادت حالة BLOCKED)، والاعتراض الصحيح لا يغيّر الملاحظة (التعديل يبقى في السجل فقط).

## ما هو منفّذ فعلاً

- سجل أدلة حتمي: بصمة الملف، وجود المقتطف، وفئة الاعتماد منقولة من سجل المصادر دون ترقية (الهيكل التنظيمي: مقترح غير معتمد؛ مصفوفة الصلاحيات: غير متحقق منها).
- آلة حالة التحدي: سلسلة أحداث مجزّأة، حد ست دورات منتجة لكل اعتراض، رفض الدورة السابعة والتكرار الحرفي، تصعيد غير المحسوم.
- بوابة القرار البشري: توقيع Ed25519 على حقول التدقيق مقابل مخزن ثقة يقدمه المستدعي؛ القيم المنطقية والسجلات غير الموقعة مرفوضة.
- سير عمل العناوين، توليد Excel وWord، فحص السرية، الاستقبال الآمن للملفات.

## ما هو محاكى

- الأدوار الثلاثة: الفريق الأسود (10 أنواع اعتراض بقواعد تغطي نحو نصف فئات البند 06.1)، المدافع (موقف ثابت لكل نوع)، المحكّم (جدول نوع × موقف).
- «المناظرة»: جدول ردود ثابت لكل نوع اعتراض؛ تتغير النتيجة بتغير الأدلة والموضع والنطاق والجهة المستلمة، لا بالاستدلال.

## ما هو منفصل أو غائب

- أوامر الإصدار (round1, append, build-excel, build-word) لا تستدعي التحدي؛ التحدي يُستدعى بأوامر منفصلة (review, challenge, adjudicate) دون إلزام.
- مخرجات المدافع (نص معدّل، إحالة) لا تُطبّق على سجل الملاحظات بأي مسار.
- لا تكامل مع مزوّد، لا عزل سياق، لا قارئ مستقل للمادة 20، لا تقييم لقابلية التطبيق.

## نتائج التقييم الأعمى

- النمط A (المحرك الحتمي على 32 حالة اصطناعية غير مسبوقة بمفتاح مختوم قبل التشغيل): كشف الاعتراضات في الفئات المغطاة 0.765 (الحد 0.80 لم يتحقق)، الفئات غير المغطاة 0.0 من 4، اعتراضات خاطئة 0.091، دقة المحكّم 0.656 (الحد 0.80 لم يتحقق)، مراجع مختلقة 0، دفاع بلا دليل 0، تصعيد 1.0.
- النمط D (عدة وكلاء حيّين معزولين في بيئة التدقيق خارج المنتج، 8 حالات): معايرة الاعتراض 0.667، مطابقة قرار المحكّم 0.833؛ اختبار التحكيم الأعمى (حجة واثقة خاطئة مقابل حجة مترددة مسندة، والعكس) حُسم بالدليل لا بالنبرة في الحالتين. هذه النتائج تثبت إمكانية التنفيذ في بيئة التشغيل لا أن المنتج يفعل ذلك.

## المطلوب للجاهزية التشغيلية

- R-01 (CRITICAL): Introduce a provider adapter layer (cdf_gco_crms/agents/providers) with a typed invocation record (17.1 fields), retries, timeouts and a mock provider clearly labelled MOCK_PROVIDER
- R-02 (CRITICAL): Role runner that builds a separate context per role (05.2–05.4 information boundaries), separate invocation per role, no shared mutable objects; keep the deterministic engine as a pre-check
- R-03 (CRITICAL): Add an `issue` command (or a --require-review flag enforced by build-excel/build-word) that refuses to build while the latest ChallengeRecord for that state hash has blockers or is absent
- R-04 (HIGH): apply_dispositions(state, record, decisions): apply UPHELD_WITH_REVISION/NARROWED/ROUTED to the ReviewState only under a verified human decision, with history
- R-05 (HIGH): Document the disposition table in 19A.6 or align it; add the blind evaluation harness (this audit's cases) to CI with a frozen key
- R-06 (HIGH): Either extend rules (existing-provision scan, fabricated-citation check, proposed-structure-as-approved, working-method overreach) or hand these to a live agent (R-01/R-02)
- R-07 (HIGH): Implement the Article 20 reader as an isolated run with a clean context (finalised draft + titles + evidence only) and the G-UX-17/R7 gate
- R-08 (HIGH): Add issued_at/valid_until and a revocation list to the trust store; load the trust store from an institution-managed location with its own signature

## حدود هذا التدقيق

- المفتاح المختوم من وضع المدقق قبل التشغيل وليس معياراً مؤسسياً؛ العينات صغيرة.
- التشغيل الحي في بيئة التدقيق استخدم وكلاء Claude Code فرعيين جدداً بسياق واحد لكل دور؛ تقييد الأدوات كان بالتعليمات لا تقنياً؛ لا إيصال من المزوّد داخل هذه البيئة.
- لم تُقيَّم متطلبات حماية البيانات السعودية لأن سياق النشر مع مزوّد غير محدد بعد.
