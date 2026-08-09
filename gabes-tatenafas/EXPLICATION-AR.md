# شرح تفصيلي للنظام — قابس تنفّس (Gabès Tatenafas)

> **الهدف**: شرح كل مكوّن من المكوّنات الأكاديمية الثلاثة، أين أُضيف بالضبط في الكود، ودوره. ثم شرح ما هو Fuzzy Mamdani الظاهر في الـ Dashboard / Diary / غيرها، وكيف يُحسب الـ score، وما المقصود بـ R1 / R2 / R3 في التوصيات.

---

## 1. التوصيات الذكية — Fuzzy Logic (Mamdani) مع دوال الانتماء

### ما هو وما الدور؟
Fuzzy Logic هو نظام منطق ضبابي يحوّل المدخلات الرقمية إلى **درجات انتماء** بدلاً من قيم ثنائية (0/1). في مشروعنا نستعمل **استدلال Mamdani** (1975) لأنه قابل للتفسير والتدقيق — كل قاعدة `IF...THEN` صريحة ويمكن للجنة المراجعة تتبّع سبب أي توصية.

### المدخلات الـ 5 (Crisp Inputs)

| المتغير | المدى | المصدر |
|---|---|---|
| `pollution` | 0..100 | `zones.pollution_level` (مُحدَّث من IQAir+WAQI) |
| `vulnerability` | 0..100 | حساسية المستخدم (طفل، مسن، ربو، حمل) |
| `symptom_severity` | 0..10 | شدّة الأعراض المبلّغ عنها في آخر 24 ساعة |
| `alerts_24h` | عدد | تنبيهات هذه الزون خلال 24 ساعة |
| `age` | بالسنوات | يُستخرج من `users.dob` |

### دوال الانتماء (Membership Functions)

كل مدخل يُحوَّل إلى 3 مجموعات ضبابية: `low` / `medium` / `high` باستخدام أشكال **شبه منحرف (trapezoid)** و**مثلث (triangle)**.

مثال: `pollution` (0..100)
```
μ_low(x)    = trapezoid(0,   0,  20, 40)    // 0 إلى 40 (انخفاض تدريجي)
μ_medium(x) = triangle (30,  50, 70)        // 30..70 (ذروة عند 50)
μ_high(x)   = trapezoid(60,  80, 100, 100)  // 60..100 (ارتفاع تدريجي)
```
عند `pollution = 75` نحصل على: `μ_low=0`, `μ_medium=0.0`, `μ_high=0.75`.

### القواعد الـ 25 (Rule Base)

ملف القواعد: `backend/config/fuzzy_rules.php`. مثال:
```
R1:  IF pollution=high  AND vulnerability=high  THEN urgency=critical (severity=0.95)
R7:  IF pollution=med   AND symptoms=high       THEN urgency=high     (severity=0.70)
R12: IF pollution=low   AND alerts_24h=low      THEN urgency=safe     (severity=0.10)
... (25 قاعدة تغطي جميع التركيبات)
```

### مراحل الاستدلال
1. **Fuzzification** — تحويل المدخلات إلى درجات انتماء.
2. **Rule Evaluation** — لكل قاعدة، تُحسب درجة التفعيل بـ `min` (AND المنطقي).
3. **Aggregation** — تُجمع نتائج القواعد بـ `max`.
4. **Defuzzification (Centroid)** — تحويل المخرَج الضبابي إلى رقم واحد:
   ```
   risk_score = Σ(μ(x) · x) / Σ(μ(x))    // مركز الكتلة
   ```

### أين أُضيف في الكود؟

| الملف | الدور | الأسطر |
|---|---|---|
| `backend/lib/fuzzy.php` | المحرك الكامل (دوال الانتماء + استدلال Mamdani + defuzzification) | ~550 سطر |
| `backend/config/fuzzy_rules.php` | تعريف الـ 5 متغيرات و 25 قاعدة | ~270 سطر |
| `backend/lib/fuzzy_context.php` | دالة موحّدة `fuzzy_for_user($pdo, $user_id)` — تُستدعى من كل endpoint | ~120 سطر |
| `db/migrations/2026-05-07-fuzzy-augment-hybrid.sql` | جدول `fuzzy_reco_logs` لتسجيل كل استنتاج (للجنة) | — |

### الـ Endpoints الـ 7 التي تستعمل Fuzzy
1. `dashboard.php` — البطاقة الخضراء "Fuzzy Mamdani" تحت التوصية
2. `diary-ai.php` — سطر "Fuzzy score X/100 (urgency)" أسفل الملخص
3. `triage.php` — تحدّد أولوية الفحص الطبي
4. `tips.php` — نصائح يومية مبنية على درجة الخطر
5. `weekly-summary.php` — ملخّص أسبوعي يقارن درجات الفُرز
6. `recommendations.php` — التوصية الأساسية (Fuzzy = صاحب القرار، LLM = صياغة لغوية فقط)
7. `chatbot.php` — يُضاف خط `[Fuzzy Mamdani · score X · level]` في كل ردّ

---

## 2. البيانات — التحقق متعدد المصادر + توليد بـ GAN

### 2.أ. التحقق المتعدد المصادر (Multi-Source Verification)

#### الدور
بدلاً من الاعتماد على API واحد قد يكون معطّلاً أو يعطي قيمة شاذة، يجمع النظام بيانات من **مصدرين** متخصصين (IQAir + WAQI) ويطبّق فلاتر إحصائية صارمة قبل قبول الرقم.

#### المراحل
1. **استخراج البيانات** من IQAir + WAQI لكل zone (باستخدام GPS).
2. **فحص المدى** (Range Check) — الرفض إذا كانت `value < 0` أو `value > 100`.
3. **كشف الشواذ (Outliers)**:
   - **IQR (Tukey 1977)**: ترفض القيمة إذا كانت `value < Q1 - 1.5·IQR` أو `value > Q3 + 1.5·IQR`.
   - **Modified Z-score (Iglewicz & Hoaglin 1993)**: ترفض إذا `|0.6745 · (value − median) / MAD| > 3.5`.
4. **التحقق المتقاطع** (Cross-zone) — لا يجوز لزون أن تختلف بـ 50 نقطة عن متوسط باقي الزونات (نشّط علم تحذير).
5. **الدمج بالوسيط** (Median Fusion) — أكثر متانة من المتوسط ضد مصدر معطوب.
6. **حساب الثقة** (Trust Score) في `[0..1]` يعتمد على تشتّت المصادر.

#### أين أُضيف؟
| الملف | الدور |
|---|---|
| `backend/lib/api_verifier.php` | المحرّك (range, IQR, Z-score, fusion, trust) |
| `backend/lib/iqair.php` | جلب IQAir + كتابة `zones.pollution_level` |
| `backend/lib/waqi.php` | جلب WAQI (سحب pollutant standardization) |
| `backend/api/verify-data.php` | endpoint admin لمشاهدة آخر 50 تحقق |
| جدول `api_verification_log` | سجلّ لكل عملية (source, raw, normalized, trust, flags) |

### 2.ب. توليد البيانات الاصطناعية (GAN في PHP خالص)

#### لماذا؟
قاعدة `risk_scores` تحوي بضع مئات من الأسطر فقط (تاريخ قصير). نماذج ML/DL تحتاج آلاف الأمثلة. الحلّ: توليد بيانات اصطناعية تشبه الأصلية إحصائياً.

#### المعمارية (Goodfellow et al. 2014، Yoon et al. 2019 — TimeGAN)
```
Generator G(z)   : z ∈ R^8 → hidden (LeakyReLU, 24) → output (tanh, 24)
                   ← يولّد سلسلة pollution لـ 24 ساعة من ضوضاء عشوائية
Discriminator D(x): x ∈ R^24 → hidden (LeakyReLU, 24) → output (sigmoid, 1)
                   ← يحكم: حقيقي (1) أم مزيف (0)

Loss = − [ log D(x_real) + log(1 − D(G(z))) ]      // Binary Cross-Entropy
Optimizer = SGD with momentum 0.9
```

كل **Backpropagation** مكتوب يدوياً (chain rule) **بدون TensorFlow ولا PyTorch** — يعمل في WAMP مباشرة.

#### الطرق الإحصائية المُكمِّلة (Iwana & Uchida 2021)
بالإضافة إلى GAN، نوفّر 4 طرق إحصائية تشتغل دائماً:
1. **Jittering** — إضافة ضوضاء غاوسية للسلسلة.
2. **Magnitude Warping** — تمدّد/ضغط السعة عبر منحنى تكعيبي.
3. **Time Warping** — تمدّد/ضغط محور الزمن.
4. **Moving-block Bootstrap** (Politis & Romano 1994) — إعادة عيّنة بأبلوك.

#### أين أُضيف؟
| الملف | الدور |
|---|---|
| `backend/lib/gan.php` | محرّك GAN كامل (~430 سطر، backprop يدوي) |
| `backend/lib/data_augment.php` | الـ 4 طرق الإحصائية + استدعاء GAN |
| `scripts/train_gan.php` | تدريب الـ GAN على بيانات `risk_scores` |
| `scripts/gan_generate.php` | توليد عيّنات وحفظها في `risk_scores_augmented` |
| `scripts/augment_data.php` | السكريبت الرئيسي (يجمع الإحصائي + GAN) |
| جدول `risk_scores_augmented` | (zone_id, score, method, fidelity_score, synthetic_at) |

---

## 3. التنبّؤ الهجين ML + DL مع المقاييس

### الدور
التنبّؤ بمستوى التلوّث في الـ 24 ساعة القادمة بدمج نموذجين يكمّلان بعضهما البعض.

### 3.أ. النموذج الأول — ML : AR(7) (Box & Jenkins 1970)
**نموذج انحدار ذاتي** يستعمل آخر 7 قيم للتنبؤ بالقيمة التالية:
```
y_t = β_0 + β_1·y_{t-1} + β_2·y_{t-2} + ... + β_7·y_{t-7}
```
يُحَل بـ **OLS مع تنظيم Ridge L2** (Hoerl & Kennard 1970) لتفادي الإفراط في التكيّف.

**لماذا 7؟** يلتقط دورة أسبوعية، ويُحقّق توازناً بين الانحياز والتباين.

### 3.ب. النموذج الثاني — DL-Inspired : Multi-EWMA Sigmoid
4 مرشّحات EWMA بثوابت زمنية مختلفة، تُدمج بـ sigmoid (مستوحى من بوّابات GRU، Cho et al. 2014):
```
EWMA(α=0.2) ──┐
EWMA(α=0.4) ──┤
EWMA(α=0.6) ──┼─→ sigmoid(W·EWMAs + b) → التنبؤ
EWMA(α=0.8) ──┘
```
`α` صغير = ذاكرة طويلة (اتجاه)، `α` كبير = استجابة سريعة (صدمات).

### 3.ج. الـ Ensemble (الدمج)
```
ŷ_final = α · ŷ_AR7 + (1 − α) · ŷ_MultiEWMA
```
`α` يُحسَّن بـ **grid-search** على 7 أيام validation hold-out (Dietterich 2000).

### 3.د. المقاييس الخمسة (Evaluation Metrics)
| المقياس | الصيغة | ماذا يقيس |
|---|---|---|
| **MAE** | `mean(|y − ŷ|)` | متوسط الخطأ المطلق |
| **RMSE** | `sqrt(mean((y − ŷ)²))` | يعاقب الأخطاء الكبيرة |
| **MAPE** | `mean(|y − ŷ| / |y|) · 100` | نسبة الخطأ المئوية |
| **R²** | `1 − SS_res/SS_tot` | نسبة التباين المُفسَّر |
| **SMAPE** | `mean(2·|y − ŷ| / (|y| + |ŷ|)) · 100` | متماثل، لا ينفجر عند y≈0 |

### أين أُضيف؟
| الملف | الدور |
|---|---|
| `backend/lib/forecast_ml.php` | AR(7) + Multi-EWMA + Ensemble (~700 سطر) |
| `backend/api/forecast-metrics.php` | يحسب ويرجع المقاييس الـ 5 (JSON) |
| `backend/api/forecast.php` | endpoint التنبؤ |
| `frontend/pages/forecast.html` | صفحة الإدمن/Health مع جدول المقارنة |
| `frontend/scripts/pages/forecast.js` | مخطّط Chart.js للتنبؤ الـ 24 ساعة |
| جدول `forecast_metrics` | تسجيل تاريخي للأداء (MAE, RMSE, ...) |
| جدول `forecast_predictions` | تسجيل كل تنبؤ مع `actual` بعدها |

---

## 4. شرح "Fuzzy Mamdani" الظاهر في الواجهة

### في Dashboard
بطاقة خضراء تحت التوصية الرئيسية تعرض:

```
┌─ Fuzzy Mamdani ─────────────────────────┐
│ Risk Score: 73.4 / 100                  │
│ Urgency Level: high                     │
│                                         │
│ Top Activated Rules:                    │
│  R1 (95%): Pollution=high & Vuln=high   │
│  R7 (62%): Pollution=med & Symp=high    │
│  R12 (28%): Alerts=med & Age>60         │
└─────────────────────────────────────────┘
```

### في Diary
سطر مضاف تحت الملخّص اليومي:
```
Fuzzy score 58.2/100 (warning) — based on PM2.5 spike at 14:00 and reported headache.
```

### في Symptoms (Triage)
شارة (badge) تظهر عند ضغط "Request AI advice":
```
[Fuzzy 67.3 · warning]
```

### في Chatbot
يُضاف سطر في نهاية كل ردّ:
```
[Fuzzy Mamdani · score 49.1 · level safe]
```

### معنى ما تراه
| العنصر | معناه |
|---|---|
| **Risk Score** | رقم 0..100 (centroid). أعلى = أخطر. |
| **Urgency Level** | `safe` (<35) ، `warning` (35..65) ، `high` (65..85) ، `critical` (>85) |
| **R1, R7, R12, ...** | أرقام القواعد المُفعَّلة من ملف `fuzzy_rules.php` |
| **النسبة المئوية بجانب Rxx** | درجة تفعيل القاعدة (`min` للمدخلات) |

---

## 5. كيف يُحسب Risk Score بالتفصيل؟

### الصيغة الكاملة (مثال محسوب يدوياً)

افترض المدخلات:
```
pollution      = 75
vulnerability  = 60
symptom_sev    = 7
alerts_24h     = 2
age            = 65
```

#### الخطوة 1 — Fuzzification
```
μ_pollution_high      = 0.75
μ_vulnerability_high  = 0.50
μ_symptom_high        = 0.85
μ_alerts_medium       = 0.60
μ_age_senior          = 0.80
```

#### الخطوة 2 — Rule Activation (مثال على 3 قواعد)
```
R1: pollution=high AND vuln=high → urgency=critical (severity=0.95)
    activation = min(0.75, 0.50) = 0.50

R7: pollution=med AND symptoms=high → urgency=high (severity=0.70)
    activation = min(0.25, 0.85) = 0.25

R12: alerts=med AND age=senior → urgency=high (severity=0.60)
    activation = min(0.60, 0.80) = 0.60
```

#### الخطوة 3 — Aggregation
نأخذ `max` لكل urgency level:
```
critical_aggregated = max(0.50 · 0.95) = 0.475
high_aggregated     = max(0.25 · 0.70, 0.60 · 0.60) = max(0.175, 0.36) = 0.36
warning_aggregated  = 0
safe_aggregated     = 0
```

#### الخطوة 4 — Defuzzification (Centroid)
نواة كل مستوى تقع في:
- safe = 17.5, warning = 50, high = 75, critical = 90

```
risk_score = (0.475·90 + 0.36·75 + 0·50 + 0·17.5) / (0.475 + 0.36 + 0 + 0)
           = (42.75 + 27.0) / 0.835
           = 83.5
urgency_level = critical  (>85 — وفي هذا المثال على الحدّ)
```

النتيجة: `Risk Score = 83.5` ، `Urgency = critical`.

---

## 6. تتبّع Recommendation كاملة

عند طلب توصية، النظام:

1. **يجمع المدخلات** من قاعدة البيانات (`zones`، `users`، `symptoms`، `alerts`).
2. **يستدعي `fuzzy_recommend(...)` ** في `backend/lib/fuzzy.php`.
3. **يحصل على**:
   - `risk_score` (نوع: float)
   - `urgency_level` (نوع: string)
   - `fired_rules[]` (قائمة بكل القواعد المُفعَّلة)
   - `explanation` (نصّ يشرح أعلى 3 قواعد)
   - `actions[]` (إجراءات مقترحة حسب urgency)
4. **يسجّل في `fuzzy_reco_logs`** (للتدقيق الأكاديمي).
5. **يرسل النتيجة إلى Groq LLM** (llama-3.3-70b) **فقط** لصياغة لغوية طبيعية. القرار الفعلي **محسوم محلياً** بـ Fuzzy.
6. **إن تعطّل Groq**، يستعمل قالب نصي محلي يدمج النتيجة الـ Fuzzy.
7. **يُعيد JSON** يحوي: `reco`، `risk_score`، `urgency`، `fired_rules`، `explanation`، `source` (`fuzzy+groq` أو `fuzzy+template`).

---

## 7. خلاصة أين كل شيء

```
backend/
├── config/
│   ├── fuzzy_rules.php       ← القواعد الـ 25
│   ├── iqair.php             ← مفتاح IQAir
│   └── waqi.php              ← مفتاح WAQI
├── lib/
│   ├── fuzzy.php             ← Mamdani engine (5 inputs, 25 rules, centroid)
│   ├── fuzzy_context.php     ← fuzzy_for_user()
│   ├── api_verifier.php      ← IQAir + WAQI fusion + IQR + Z-score
│   ├── iqair.php             ← Live IQAir fetcher
│   ├── waqi.php              ← Live WAQI fetcher
│   ├── data_augment.php      ← Statistical aug (jitter/warp/bootstrap)
│   ├── gan.php               ← Pure-PHP GAN (G + D + backprop)
│   ├── forecast_ml.php       ← AR(7) + Multi-EWMA + Ensemble + 5 metrics
│   └── helpers.php           ← compute_risk_score(), global_status()
└── api/
    ├── dashboard.php         ← fuzzy_for_user()
    ├── diary-ai.php          ← fuzzy_for_user()
    ├── triage.php            ← fuzzy_for_user()
    ├── tips.php              ← fuzzy_for_user()
    ├── weekly-summary.php    ← fuzzy_for_user()
    ├── recommendations.php   ← fuzzy_recommend() + Groq wrapper
    ├── chatbot.php           ← fuzzy_for_user() + Groq
    ├── verify-data.php       ← Admin: voir api_verification_log
    ├── forecast.php          ← AR7 + Multi-EWMA prediction
    └── forecast-metrics.php  ← MAE, RMSE, MAPE, R², SMAPE

scripts/
├── augment_data.php          ← CLI: stat aug (active toujours)
├── train_gan.php             ← CLI: train GAN PHP
├── gan_generate.php          ← CLI: générer samples GAN
└── refresh_pollution.php     ← CLI: live IQAir+WAQI refresh

db/migrations/
├── 2026-05-07-fuzzy-augment-hybrid.sql  ← fuzzy_reco_logs, augmented, metrics
└── 2026-05-13-zones-real-positions.sql  ← 6 zones with real GPS
```

---

## 8. مراجع أكاديمية للذكر في المذكّرة

1. **Mamdani, E.H. (1975)** — *Application of fuzzy algorithms for control of simple dynamic plant*. Proc. IEE.
2. **Goodfellow, I. et al. (2014)** — *Generative Adversarial Nets*. NeurIPS.
3. **Yoon, J. et al. (2019)** — *Time-series Generative Adversarial Networks (TimeGAN)*. NeurIPS.
4. **Iwana, B.K. & Uchida, S. (2021)** — *Empirical survey of data augmentation for time series classification*. PLOS ONE.
5. **Box, G.E.P. & Jenkins, G.M. (1970)** — *Time Series Analysis: Forecasting and Control*.
6. **Hoerl, A.E. & Kennard, R.W. (1970)** — *Ridge regression*. Technometrics.
7. **Cho, K. et al. (2014)** — *Learning Phrase Representations using RNN Encoder-Decoder for Statistical Machine Translation* (GRU).
8. **Dietterich, T. (2000)** — *Ensemble Methods in Machine Learning*. MCS.
9. **Tukey, J.W. (1977)** — *Exploratory Data Analysis* (IQR rule).
10. **Iglewicz, B. & Hoaglin, D.C. (1993)** — *How to Detect and Handle Outliers*.
11. **Politis, D.N. & Romano, J.P. (1994)** — *The Stationary Bootstrap*. JASA.
