# 刘辉羽毛球练习处方模板

Use this template when the user asks how to practice, asks for a plan, or needs a progression after a diagnosis. Keep plans evidence-backed and proportional to the user's context. Apply `practice-plan-rules.json`; the 15-minute structure is a fallback, not a fixed prescription.

## When To Use

- The user asks "怎么练", "给我一个计划", "练习方法", "多久能改", or similar.
- The diagnosis includes a repeatable correction cue from retrieved evidence.
- The user wants a training structure rather than only an explanation.

## Required Output

Before writing the plan, identify or conservatively assume: current level, singles/doubles use, available practice setup, session duration, handedness when technically relevant, and any pain or injury signal. State material assumptions in one line. Ask at most one concise question when the missing answer would change safety or make the drill impossible; otherwise give a solo fallback and a fed-drill upgrade.

### 今日 15 分钟

Rename this heading to the user's available duration when one is given, and scale all segments to that exact total. Do not silently force every user into 15 minutes.

- **热身 3 分钟**: choose a low-risk movement related to the topic.
- **技术分解 5 分钟**: isolate one correction cue.
- **节奏/多球 5 分钟**: add timing, feeding, or movement pressure.
- **自测 2 分钟**: give one observable success standard.

### 3 天修正

- Day 1: slow isolation and correct feeling.
- Day 2: add movement or incoming-ball pressure.
- Day 3: add decision-making or rally context.

### 2 周巩固

- Week 1: repeat the cue under controlled feeds; stop when quality drops.
- Week 2: test the cue in half-court or point-like situations.

### 自测标准

Give 2-4 standards that can be checked without a coach, such as timing, contact point, recovery, shuttle trajectory, or error rate.

### 常见错误

List 2-3 likely errors from retrieved evidence. Do not invent injury, biomechanics, or tactical claims without source support.

### 暂停或复核信号

Mention pain, repeated loss of balance, declining movement quality, or uncertainty that requires video review. If the user already reports pain or injury, do not prescribe through it: stop the related movement and recommend assessment by a qualified clinician or physiotherapist before resuming.

### 来源证据

Cite one to three source videos with timestamp ranges. If a plan element is inferred from a principle rather than directly stated, say so.

## Plan Rules

- Use only one main correction cue per plan unless the user asks for a broader program.
- Prefer ready entries and curated entries.
- Treat `needs_visual_review` entries as leads, not final proof.
- Scale volume conservatively for amateur players.
- Distinguish a beginner's fixed-feed progression from intermediate decision practice and advanced random-pressure work.
- Distinguish singles recovery/coverage from doubles partner responsibilities; do not generalize one format's positioning rule to the other.
- Never prescribe partner feeding to a solo user without a feasible solo substitute.
- Include rest or quality-stop rules when the drill is high intensity.
- Do not promise outcomes by a fixed date.
