# 回答质量黄金集审核队列

知识库版本：`2026-07-18T08:28:39.249248+00:00`
候选问题：`30`
可进入自动回归：`30`
仍待审核：`0`

问题类型：`diagnosis` 6 条、`evidence_boundary` 5 条、`tactics` 7 条、`technical_action` 10 条、`training_plan` 2 条

## 审核方法

1. 维护者核对问题理解、推荐视频、转写和 Review notes，写出必须覆盖的文字要点、证据视频、适用边界和禁止断言。
2. 审核关注来源忠实度和用户问题是否被正确理解；回答质量通过自动回归与后续用户反馈持续改进。
3. 在每题的 `Review notes` JSON 块中填写审核意见；不要改字段名或删除案例。
4. 先运行 `python3 scripts/apply_answer_quality_review_notes.py --dry-run` 校验，再去掉 `--dry-run` 原子写回黄金集。
5. 机器候选只是减轻找视频的工作量，不是黄金答案；`draft` 案例不会进入自动回答回归。

## AQ001 · 后场被动来不及架拍怎么把球打到底线

- 类型：`diagnosis`
- 预期模式：`balanced`
- 来源：`retrieval_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [被动高远 别说这样容易抡大臂，不这样偷出来时间抢架拍位置也是个输，真被动就没时间侧身，没时间架拍，没空间做正常架拍了，所以大家总说职业选手不架拍，其实架了，只不过没做那么主动的架拍罢了](https://www.douyin.com/video/7558912953539071292) (`7558912953539071292`)
- 必看候选: [后场框架应用 如果基础好，可以推荐出快速框架，之前发过很多爆发力出框架的作品！但是顶肘动作小带来效率的同时，也会因为顶肘动作小而削弱摆臂的幅度而失去力量！如果没有的专业力量的的朋友推荐第二种，但是要注意是拍低肘不低！不然会导致错误顶肘成为错误动作！ 总结，快速框架优点是容易做速度快效率高！缺点不好发力 动态低架优点是，容错率高，省力！缺点是不好学习 普通的架拍，优点是都能兼顾，缺点是该来不及的还是来不及](https://www.douyin.com/video/7589749293205363633) (`7589749293205363633`)
- 必看候选: [被动肯定要发力，但是要把力量使用在挥拍的速度上，而不是动作的幅度](https://www.douyin.com/video/7153445193713290511) (`7153445193713290511`)
- 必看候选: [反手被动高远 虽然被动，但是放松发力更重要，别说示范的球不到位，也打出界一米了，主要是在底线摄像机放不下了](https://www.douyin.com/video/7546109410041908538) (`7546109410041908538`)

### 机器补充候选

- 没有额外候选。

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7558912953539071292"
  ],
  "required_video_ids": [
    "7558912953539071292",
    "7589749293205363633",
    "7153445193713290511",
    "7546109410041908538"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "先判断是否真正处于被动；真被动时不强求完整侧身和主动架拍。",
      "acceptable_terms": [
        "真被动",
        "来不及侧身",
        "被动架拍"
      ],
      "evidence_video_ids": [
        "7558912953539071292",
        "7589749293205363633"
      ]
    },
    {
      "description": "缩短准备过程并尽早向上击球；击球点落后时收拍方向也会相应偏后。",
      "acceptable_terms": [
        "尽早击球",
        "向上击球",
        "收拍在后"
      ],
      "evidence_video_ids": [
        "7558912953539071292"
      ]
    },
    {
      "description": "把力量用于挥拍速度和身体传导，不用盲目放大动作幅度。",
      "acceptable_terms": [
        "挥拍速度",
        "力量传导",
        "动作幅度"
      ],
      "evidence_video_ids": [
        "7153445193713290511"
      ]
    },
    {
      "description": "正手头顶被动与反手被动是两条不同处理分支。",
      "acceptable_terms": [
        "正手头顶",
        "反手被动",
        "不同分支"
      ],
      "evidence_video_ids": [
        "7558912953539071292",
        "7546109410041908538"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "仅凭问题无法确认被动程度、来球位置以及正手头顶还是反手处理，需要结合用户视频。",
      "acceptable_terms": [
        "来球位置",
        "动作视频",
        "正手还是反手"
      ]
    }
  ],
  "forbidden_claims": [
    "越被动动作越要做大",
    "被动球必须完整侧身",
    "打到底线只靠手腕"
  ],
  "notes": "保留被动高远主证据，补入快速框架与正反手分支；来源与必答要点已进入自动回归。"
}
```

## AQ002 · 杀球不重没有威胁怎么办

- 类型：`diagnosis`
- 预期模式：`balanced`
- 来源：`retrieval_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [杀球瞄准 杀球瞄准 卢迦彧的杀球不是那种很重的，所以落点上就尤为重要，比赛中非常容易被防守反击!中间涉及到了张指导的肖像权，已经经过了前辈本人的同意!](https://www.douyin.com/video/7659348110628345210) (`7659348110628345210`)
- 必看候选: [不同杀球 给大家解释为什么每个运动员动作不一样，其实在我的视角里，都是脚蹬地开始发力传递到球拍，但是每个人有差异，比如有的胳膊有劲儿，有的腰腹有劲儿，有的手腕有劲儿，通过漫长的训练，无意识的找到最适合自己发力配比，所以大家学习也得根据自己情况来](https://www.douyin.com/video/7567155406117533051) (`7567155406117533051`)
- 必看候选: [重杀框架 可以和期一起看，不同的框架可以决定不同的杀球](https://www.douyin.com/video/7659991105622862457) (`7659991105622862457`)
- 必看候选: [压球新讲 就算追求贴球发力，也得是建立在能把动作做完的基础上贴，怕打不到球也会本能的把球拍接近球而失去发力空间，这都是不对的](https://www.douyin.com/video/7440406891664133428) (`7440406891664133428`)

### 机器补充候选

- 机器候选: [反手杀球 不同的击球位置也会使用不同的动作,都有不同的效果](https://www.douyin.com/video/7550305145877155131) (`7550305145877155131`)
- 机器候选: [发力第二集 大家不要错误的去伸胳膊，要学会利用身体去拿高点](https://www.douyin.com/video/7485692231404342586) (`7485692231404342586`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7659348110628345210"
  ],
  "required_video_ids": [
    "7659348110628345210",
    "7567155406117533051",
    "7659991105622862457",
    "7440406891664133428"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "杀球威胁不只来自绝对球速；更尖、更靠边并能衔接下一拍也能制造威胁。",
      "acceptable_terms": [
        "更尖",
        "更靠边",
        "下一拍"
      ],
      "evidence_video_ids": [
        "7659348110628345210"
      ]
    },
    {
      "description": "杀球力量来自从下肢和身体传到球拍的整体链条，但每个人的手指、手臂和腰腹配比不同。",
      "acceptable_terms": [
        "脚蹬地",
        "传到球拍",
        "发力配比"
      ],
      "evidence_video_ids": [
        "7567155406117533051"
      ]
    },
    {
      "description": "要给挥拍留下足够的拍球间距和完成动作的空间，避免贴得过近。",
      "acceptable_terms": [
        "发力空间",
        "离球远一点",
        "动作做完"
      ],
      "evidence_video_ids": [
        "7440406891664133428"
      ]
    },
    {
      "description": "快速突击与重杀使用的框架和目标不同，不能只追求同一种大力动作。",
      "acceptable_terms": [
        "快速突击",
        "重杀框架",
        "不同框架"
      ],
      "evidence_video_ids": [
        "7659991105622862457",
        "7659348110628345210"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "需要区分单打或双打、快速突击或重杀，并结合用户动作才能定位具体薄弱环节。",
      "acceptable_terms": [
        "单打或双打",
        "快速突击",
        "动作视频"
      ]
    }
  ],
  "forbidden_claims": [
    "杀球不重唯一原因是手腕没压",
    "所有人都应复制同一套杀球动作",
    "动作越大杀球一定越重"
  ],
  "notes": "将落点、个体化动力链、重杀框架和击球空间分开标注；机器候选中的反手杀球不作为通用主证据。"
}
```

## AQ003 · 网前框架怎么做才不会身体僵硬

- 类型：`technical_action`
- 预期模式：`balanced`
- 来源：`retrieval_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [网前框架 这样做不但不会让新手组织框架失误，还能减少身体僵硬](https://www.douyin.com/video/7661940775983482097) (`7661940775983482097`)

### 机器补充候选

- 机器候选: [网前撤后场手部细节 场景是网前撤后场，不是中场撤后场，只要把肘先抬起来到合适的位置怎么抬怎么摆都可以](https://www.douyin.com/video/7486788550298471739) (`7486788550298471739`)
- 机器候选: [滚网搓球 双打网前有人看守时有奇效](https://www.douyin.com/video/7509355373729762619) (`7509355373729762619`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7661940775983482097"
  ],
  "required_video_ids": [
    "7661940775983482097"
  ],
  "irrelevant_video_ids": [
    "7384641787647872308",
    "7589749293205363633"
  ],
  "required_text_points": [
    {
      "description": "网前框架应在抬拍和接近来球的过程中逐步形成，避免提前伸直并锁死手臂。",
      "acceptable_terms": [
        "逐步形成",
        "抬拍过程",
        "避免锁死"
      ],
      "evidence_video_ids": [
        "7661940775983482097"
      ]
    },
    {
      "description": "框架要保留对来球高度、方向和节奏的调整空间，先放松再组织。",
      "acceptable_terms": [
        "调整空间",
        "来球高度",
        "先放松"
      ],
      "evidence_video_ids": [
        "7661940775983482097"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "手、拍面和身体的精确相对位置依赖动态画面，文字不能替代动作示范。",
      "acceptable_terms": [
        "动态画面",
        "精确位置",
        "动作示范"
      ]
    }
  ],
  "forbidden_claims": [
    "手臂应该提前伸直锁死",
    "网前框架越固定越好",
    "只要夹紧身体就不会失误"
  ],
  "notes": "只保留直接讲网前框架的视频；两个后场框架视频容易造成场景混用，已排除。"
}
```

## AQ004 · 双打接发怎么抢主动

- 类型：`tactics`
- 预期模式：`text_primary`
- 来源：`retrieval_cases+answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [双打发接发 永远考虑对手出球最快的位置，慢的位置球真来了再说](https://www.douyin.com/video/7501542236061420859) (`7501542236061420859`)
- 必看候选: [接发准备 每个人都要清楚做动作的目的性，不能盲目学习](https://www.douyin.com/video/7639306481355832689) (`7639306481355832689`)
- 必看候选: [中低手位切腰](https://www.douyin.com/video/7591112983016940977) (`7591112983016940977`)

### 机器补充候选

- 没有额外候选。

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7501542236061420859"
  ],
  "required_video_ids": [
    "7501542236061420859",
    "7639306481355832689",
    "7591112983016940977"
  ],
  "irrelevant_video_ids": [
    "7113001319694224655",
    "7072543702161296640"
  ],
  "required_text_points": [
    {
      "description": "接发先覆盖对手最快能打出的线路，并根据明显停顿或节奏变化再调整判断。",
      "acceptable_terms": [
        "最快的位置",
        "明显停顿",
        "节奏变化"
      ],
      "evidence_video_ids": [
        "7501542236061420859"
      ]
    },
    {
      "description": "准备动作要有目的性：降低重心、保持紧凑稳定的持拍位置，同时能兼顾偷后场。",
      "acceptable_terms": [
        "目的性",
        "重心",
        "防偷球"
      ],
      "evidence_video_ids": [
        "7639306481355832689"
      ]
    },
    {
      "description": "根据接球高度选择推、放、切腰或先控制，不把所有球都处理成扑网。",
      "acceptable_terms": [
        "推可以放",
        "切腰",
        "接球高度"
      ],
      "evidence_video_ids": [
        "7639306481355832689",
        "7591112983016940977"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "判断会随发球位置、发球者持拍手、接发者能力以及是否可能偷后场而变化。",
      "acceptable_terms": [
        "发球位置",
        "持拍手",
        "偷后场"
      ]
    }
  ],
  "forbidden_claims": [
    "双打接发永远只扑网",
    "接发时只需要猜一个方向",
    "发球方抢主动的动作就是接发动作"
  ],
  "notes": "原必看两条都站在发球方讲主动性，已移入排除；补入接发准备和中低手位切腰。"
}
```

## AQ005 · 平抽挡怎么提高连续速度

- 类型：`technical_action`
- 预期模式：`balanced`
- 来源：`retrieval_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [抽球细节 面对快球，假设球一共飞行0.8秒到你的击球点，如果你光伸拍做框架就用了0.5秒，那就没法打了，但是如果0.3秒就能做好框架，你就有0.5秒可以挥拍](https://www.douyin.com/video/7560064232592493882) (`7560064232592493882`)
- 必看候选: [握拍微调 抽挡反手为主，尽量不做正反手转换](https://www.douyin.com/video/7447084061371272507) (`7447084061371272507`)
- 必看候选: [抽挡连贯 我知道有些兄弟很要强，受不了这种屈辱，就是不能承认被动，没关系，打羽毛球吧，它一定会教会你](https://www.douyin.com/video/7506736569824726332) (`7506736569824726332`)
- 必看候选: [高速对抗步法 小姐姐是两省冠军🏆，这种情况属于高速对抗状态下，就是球都比较平，没有侧身的时间和意义](https://www.douyin.com/video/7652440366436945017) (`7652440366436945017`)

### 机器补充候选

- 机器候选: [4280 多点位抽球应用 这种准备就是应对快速腹部胸口位置的准备，可以有效的优化两边的出拍速度的合理性，一般对口抽挡中](https://www.douyin.com/video/7663523942439940453) (`7663523942439940453`)
- 机器候选: [压抽才是双打的主旋律，没人一上来就挑给你](https://www.douyin.com/video/7205399670959459623) (`7205399670959459623`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7560064232592493882"
  ],
  "required_video_ids": [
    "7560064232592493882",
    "7447084061371272507",
    "7506736569824726332",
    "7652440366436945017"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "连续速度首先来自更快完成紧凑框架并给挥拍留出时间，击球与落地节奏要连贯。",
      "acceptable_terms": [
        "快速框架",
        "留出时间",
        "击球与落地"
      ],
      "evidence_video_ids": [
        "7560064232592493882"
      ]
    },
    {
      "description": "高速抽挡以反手握拍为主做小幅微调，减少完整正反手握拍转换。",
      "acceptable_terms": [
        "反手为主",
        "握拍微调",
        "不做正反手转换"
      ],
      "evidence_video_ids": [
        "7447084061371272507"
      ]
    },
    {
      "description": "被动时先降低重心和框架保护身体侧，回球变平后再抬高框架主动抽压。",
      "acceptable_terms": [
        "承认被动",
        "保护身体",
        "抬高框架"
      ],
      "evidence_video_ids": [
        "7506736569824726332"
      ]
    },
    {
      "description": "高速平球对抗通常没有完整侧身的时间，应保持正面并缩短还原。",
      "acceptable_terms": [
        "高速对抗",
        "没有侧身时间",
        "正面"
      ],
      "evidence_video_ids": [
        "7652440366436945017"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "主动平抽、被动挡球和不同击球高度的动作重点不同，需要按场景调整。",
      "acceptable_terms": [
        "主动平抽",
        "被动挡球",
        "击球高度"
      ]
    }
  ],
  "forbidden_claims": [
    "每一拍都要完整切换正反手握拍",
    "挥拍幅度越大连续速度越快",
    "高速抽挡必须完整侧身"
  ],
  "notes": "机器补充候选比原主证据更直接，已将抽球框架视频升为主证据。"
}
```

## AQ006 · 启动慢而且回动不及时怎么练

- 类型：`training_plan`
- 预期模式：`balanced`
- 来源：`retrieval_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [步法节奏 越着急跑输的越快，中场待着不动也不行，所以只能去找到这个接球的节奏](https://www.douyin.com/video/7571574635323124145) (`7571574635323124145`)
- 必看候选: [其实接慢节奏，是很难找到启动点的](https://www.douyin.com/video/7158640349798255907) (`7158640349798255907`)
- 必看候选: [回动步法合理性 每个人的合理也不一样，有的人腿的力量强，并步能并很远，所以还要结合自己的情况](https://www.douyin.com/video/7643719807951615482) (`7643719807951615482`)
- 必看候选: [分解步法种类繁多，这是练启动有代表性的，一轮一口气做完，做3组。我肯定是没做到10秒钟，要不视频太长😓](https://www.douyin.com/video/7056244399390412064) (`7056244399390412064`)

### 机器补充候选

- 机器候选: [并不是说一定要一步回位。而是体现向左回动，左脚的重要性](https://www.douyin.com/video/7059589039694957864) (`7059589039694957864`)
- 机器候选: [后场就是刻意练的被动步法，不是不积极，主要练回动的节奏感](https://www.douyin.com/video/7280727710740139264) (`7280727710740139264`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7571574635323124145"
  ],
  "required_video_ids": [
    "7571574635323124145",
    "7158640349798255907",
    "7643719807951615482",
    "7056244399390412064"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "先区分纯移动速度慢与判断、节奏慢；回位后要在对手击球时完成预动或启动。",
      "acceptable_terms": [
        "判断节奏",
        "对手击球",
        "启动"
      ],
      "evidence_video_ids": [
        "7571574635323124145"
      ]
    },
    {
      "description": "击球后不要停在原地，先稳定身体并及时回动，再进入观察和启动节奏。",
      "acceptable_terms": [
        "不要停留",
        "及时回动",
        "稳定身体"
      ],
      "evidence_video_ids": [
        "7158640349798255907"
      ]
    },
    {
      "description": "并步、交叉步等回位方式要按距离和能力选择，避免用过多碎步套一个固定答案。",
      "acceptable_terms": [
        "距离和能力",
        "并步",
        "交叉步"
      ],
      "evidence_video_ids": [
        "7643719807951615482"
      ]
    },
    {
      "description": "给出按用户时长或默认15分钟分配的热身、启动分解、节奏练习和自测，并附3天及2周进阶。",
      "acceptable_terms": [
        "15分钟",
        "3天修正",
        "2周巩固"
      ],
      "evidence_video_ids": [
        "7056244399390412064",
        "7571574635323124145"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "计划需说明水平、单双打、独练或有喂球者和时长等假设。",
      "acceptable_terms": [
        "水平",
        "单双打",
        "独练"
      ]
    },
    {
      "description": "出现疼痛、连续失衡或动作明显变形时应停止或降低难度。",
      "acceptable_terms": [
        "疼痛",
        "失去平衡",
        "降低难度"
      ]
    }
  ],
  "forbidden_claims": [
    "练一个月一定能解决启动慢",
    "所有距离都只能用同一种回位步法",
    "每天都应该用最大强度练启动"
  ],
  "notes": "补入击球后回动证据，并把训练题按项目练习处方规则设为可执行计划；技术部分由证据回归与用户反馈持续校正。"
}
```

## AQ007 · 吊球怎么和杀球配合拉开对手

- 类型：`tactics`
- 预期模式：`balanced`
- 来源：`retrieval_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [吊球和刹球要相互配合使用，拉扯对手防守的站位，一味的强攻很容易被防反](https://www.douyin.com/video/7115241358255803683) (`7115241358255803683`)
- 必看候选: [软压还包括点杀，远网吊球等等](https://www.douyin.com/video/7093706918492917033) (`7093706918492917033`)
- 必看候选: [杀球瞄准 杀球瞄准 卢迦彧的杀球不是那种很重的，所以落点上就尤为重要，比赛中非常容易被防守反击!中间涉及到了张指导的肖像权，已经经过了前辈本人的同意!](https://www.douyin.com/video/7659348110628345210) (`7659348110628345210`)

### 机器补充候选

- 没有额外候选。

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7115241358255803683"
  ],
  "required_video_ids": [
    "7115241358255803683",
    "7093706918492917033",
    "7659348110628345210"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "杀球和吊球要交替配合以拉扯对手的防守站位，避免连续无条件强攻被反击。",
      "acceptable_terms": [
        "相互配合",
        "拉扯",
        "防守站位"
      ],
      "evidence_video_ids": [
        "7115241358255803683"
      ]
    },
    {
      "description": "自身位置不好时用软压、点杀或远网吊球保持下压并连接下一拍，不勉强全力杀。",
      "acceptable_terms": [
        "位置不好",
        "软压",
        "下一拍"
      ],
      "evidence_video_ids": [
        "7093706918492917033"
      ]
    },
    {
      "description": "杀球选择还要考虑落点、回位和下一拍，而不只是力量。",
      "acceptable_terms": [
        "落点",
        "回位",
        "下一拍"
      ],
      "evidence_video_ids": [
        "7659348110628345210"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "主证据是单打后场战术；双打还必须结合搭档封网和轮转条件。",
      "acceptable_terms": [
        "单打",
        "双打",
        "搭档"
      ]
    }
  ],
  "forbidden_claims": [
    "每个到位球都应该全力重杀",
    "吊球只是没有威胁的过渡球",
    "只要杀吊交替就不需要回位"
  ],
  "notes": "把两个只讲吊球技术的原必看降为非必选，补入软压和落点衔接证据。"
}
```

## AQ008 · 接杀以后怎么防守反击

- 类型：`tactics`
- 预期模式：`balanced`
- 来源：`retrieval_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [单打防守反击](https://www.douyin.com/video/7602766054809333617) (`7602766054809333617`)
- 必看候选: [双打防守思路 你总会遇到你挑不起来的进攻](https://www.douyin.com/video/7621243051541587889) (`7621243051541587889`)
- 必看候选: [模拟的防守挡斜线随后抢网反击](https://www.douyin.com/video/7127470220309957923) (`7127470220309957923`)

### 机器补充候选

- 机器候选: [快@ 你们的女搭档来学习吧](https://www.douyin.com/video/7087759120761228578) (`7087759120761228578`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7602766054809333617"
  ],
  "required_video_ids": [
    "7602766054809333617",
    "7621243051541587889",
    "7127470220309957923"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "接杀后的第一目标是稳定控制回球质量；攻击质量太高时先中和而不是强行反攻。",
      "acceptable_terms": [
        "先控制",
        "回球质量",
        "先中和"
      ],
      "evidence_video_ids": [
        "7602766054809333617",
        "7621243051541587889"
      ]
    },
    {
      "description": "单打可根据进攻者移动方向和空当选择变线，让对方难以连续追击。",
      "acceptable_terms": [
        "移动方向",
        "空当",
        "变线"
      ],
      "evidence_video_ids": [
        "7602766054809333617"
      ]
    },
    {
      "description": "双打要同时观察前场队员和搭档位置；无法高质量起球时再考虑平抽或变线。",
      "acceptable_terms": [
        "前场队员",
        "搭档位置",
        "变线"
      ],
      "evidence_video_ids": [
        "7621243051541587889"
      ]
    },
    {
      "description": "挡网后先看对方击球，再突然加速上网，不要接完球盲目前冲。",
      "acceptable_terms": [
        "先观察",
        "突然加速",
        "上网"
      ],
      "evidence_video_ids": [
        "7127470220309957923"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "单双打、来球质量和接球高度会改变反击选择，并非每个接杀都能直接反攻。",
      "acceptable_terms": [
        "单双打",
        "来球质量",
        "并非每个"
      ]
    }
  ],
  "forbidden_claims": [
    "所有接杀都应该挡斜线",
    "接杀以后必须立刻冲网",
    "防守反击只需要盯着球"
  ],
  "notes": "三条证据分别覆盖单打、双打和挡网后启动，保留场景边界。"
}
```

## AQ009 · 发小球怎么增加隐蔽性并偷后场

- 类型：`technical_action`
- 预期模式：`balanced`
- 来源：`retrieval_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [反手发后场 现在的规则是不超过1.15高度就可以，其实不用太在乎球拍在哪结束](https://www.douyin.com/video/7508222669708463420) (`7508222669708463420`)
- 必看候选: [反手发球 种类非常多，我就讲的一种比较好上手的，比较稳定的](https://www.douyin.com/video/7522041413614816570) (`7522041413614816570`)
- 必看候选: [发小球进阶 大家总是关注球飞的贴不贴，贴当然重要，但是力量控制到过网能落也很重要](https://www.douyin.com/video/7589590613499595185) (`7589590613499595185`)
- 必看候选: [发球变化 发球隐蔽是非常重要的](https://www.douyin.com/video/7483346020332522812) (`7483346020332522812`)

### 机器补充候选

- 机器候选: [正手发小球的教学，以前的作品里有，没有好的发球，只有合适的发球](https://www.douyin.com/video/7254755365995285812) (`7254755365995285812`)
- 机器候选: [被偷后场再也不用报警啦](https://www.douyin.com/video/7124871920230632745) (`7124871920230632745`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7508222669708463420"
  ],
  "required_video_ids": [
    "7508222669708463420",
    "7522041413614816570",
    "7589590613499595185",
    "7483346020332522812"
  ],
  "irrelevant_video_ids": [
    "7113001319694224655"
  ],
  "required_text_points": [
    {
      "description": "短发与偷后场应尽量共享准备姿态、出手顺序和前段节奏，到较晚阶段才改变线路。",
      "acceptable_terms": [
        "准备姿态",
        "相同节奏",
        "晚阶段"
      ],
      "evidence_video_ids": [
        "7508222669708463420",
        "7483346020332522812"
      ]
    },
    {
      "description": "先保证小球过网后的下降质量，弧线最高点应靠近网带，偷后场只是变化。",
      "acceptable_terms": [
        "最高点",
        "网带",
        "下降"
      ],
      "evidence_video_ids": [
        "7589590613499595185",
        "7522041413614816570"
      ]
    },
    {
      "description": "反手偷后场的准备手位要给肘和前臂留下加速空间，不要一开始把手抬死。",
      "acceptable_terms": [
        "肘",
        "加速空间",
        "准备手位"
      ],
      "evidence_video_ids": [
        "7508222669708463420"
      ]
    },
    {
      "description": "双打反手发小球需要控制前臂和手腕幅度，以稳定和减速为先。",
      "acceptable_terms": [
        "反手发小球",
        "控制手腕",
        "稳定"
      ],
      "evidence_video_ids": [
        "7522041413614816570"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "以上按双打反手发球理解；单打正手发球是另一套动作与战术，应先确认场景。",
      "acceptable_terms": [
        "双打反手",
        "单打正手",
        "确认场景"
      ]
    }
  ],
  "forbidden_claims": [
    "手腕甩得越大偷后场越隐蔽",
    "偷后场次数越多越能抢主动",
    "正手发球和反手发球动作完全相同"
  ],
  "notes": "原必看混入正手发球内容，已改为双打反手短发、偷后场、过网弧线与晚变线证据。"
}
```

## AQ010 · 握拍太紧挥拍僵硬怎么放松

- 类型：`diagnosis`
- 预期模式：`video_primary`
- 来源：`retrieval_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [半拳式握拍是发力必备的握拍，没有半拳式，基本出现不了鞭甩，因为大拇指会卡住](https://www.douyin.com/video/7086276287681137961) (`7086276287681137961`)
- 必看候选: [正常击球位置的握拍，没有商量的，特殊位置有可能会握拍微调](https://www.douyin.com/video/7213191190382972172) (`7213191190382972172`)

### 机器补充候选

- 机器候选: [放松架拍 没有说对错，是很多人还不会自然传动力量就开始锁定身体，锁住力量是为了让会发力的人爆发力最大化，不会发力的只会更僵硬](https://www.douyin.com/video/7628342769941691121) (`7628342769941691121`)
- 机器候选: [网前框架 这样做不但不会让新手组织框架失误，还能减少身体僵硬](https://www.douyin.com/video/7661940775983482097) (`7661940775983482097`)
- 机器候选: [基础挥拍重快 由于要控制时长我剪辑的很精简，基础挥拍如何打的重，如何打的快，建议多看两边，详细的我们直播间来说](https://www.douyin.com/video/7383154379915906319) (`7383154379915906319`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7086276287681137961"
  ],
  "required_video_ids": [
    "7086276287681137961",
    "7213191190382972172"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "准备阶段保持松弛，击球瞬间用手指短暂收紧；放松不等于全程松脱球拍。",
      "acceptable_terms": [
        "准备阶段",
        "击球瞬间",
        "短暂收紧"
      ],
      "evidence_video_ids": [
        "7086276287681137961"
      ]
    },
    {
      "description": "用半拳式握拍并保留虎口和掌心空间，让食指参与控制和发力转换。",
      "acceptable_terms": [
        "半拳式",
        "虎口",
        "食指"
      ],
      "evidence_video_ids": [
        "7086276287681137961"
      ]
    },
    {
      "description": "正常击球位置使用基础握拍，特殊或被动位置才做有目的的小幅调整。",
      "acceptable_terms": [
        "正常击球位置",
        "特殊位置",
        "握拍微调"
      ],
      "evidence_video_ids": [
        "7213191190382972172"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "握拍压力和手指位置依赖视觉检查；仅凭文字不能确认用户是否真正放松。",
      "acceptable_terms": [
        "视觉检查",
        "握拍压力",
        "不能确认"
      ]
    }
  ],
  "forbidden_claims": [
    "从准备到击球都要死死握拍",
    "击球时手指也必须完全放松",
    "挥拍僵硬只要压手腕就能解决"
  ],
  "notes": "保留半拳式与标准握拍两条互补证据；具体手型仍需视频学习并需结合视频学习。"
}
```

## AQ011 · 双打轮转时什么时候补位

- 类型：`tactics`
- 预期模式：`text_primary`
- 来源：`answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [双打实战轮转 无论训练时有多么默契，实战中都会有配合失误，那实战看的就是两个人的容错够不够](https://www.douyin.com/video/7614167503938610417) (`7614167503938610417`)
- 必看候选: [中腰球出来，出现轮转的可能性很大](https://www.douyin.com/video/7106697344128748835) (`7106697344128748835`)

### 机器补充候选

- 机器候选: [双打抓回头 紫电青霜不要去掉低胶，如果一定要去掉低胶，或者已经去掉底胶，就要考虑结合自己的能力，也要换掉拍头的连钉，普通的线孔就在盒子里赠送了的](https://www.douyin.com/video/7656927370758796145) (`7656927370758796145`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7614167503938610417"
  ],
  "required_video_ids": [
    "7614167503938610417",
    "7106697344128748835"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "轮转不是固定口令，而是由来球线路、前场搭档移动和暴露空当共同触发。",
      "acceptable_terms": [
        "来球线路",
        "搭档移动",
        "空当"
      ],
      "evidence_video_ids": [
        "7614167503938610417",
        "7106697344128748835"
      ]
    },
    {
      "description": "前场队员的移动先给出轮转方向，后场队员应补其让出的区域并避免两人抢同一点。",
      "acceptable_terms": [
        "前场队员",
        "让出的区域",
        "避免碰撞"
      ],
      "evidence_video_ids": [
        "7614167503938610417"
      ]
    },
    {
      "description": "中腰球常会触发轮转，但要看搭档是否已让开以及回球是直线、中路还是斜线。",
      "acceptable_terms": [
        "中腰球",
        "搭档让开",
        "直线"
      ],
      "evidence_video_ids": [
        "7106697344128748835"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "进攻与防守阵型、实际击球线路和沟通状态不同，补位答案也会改变。",
      "acceptable_terms": [
        "进攻与防守",
        "击球线路",
        "沟通"
      ]
    }
  ],
  "forbidden_claims": [
    "任何中腰球都必须轮转",
    "前场队员永远不需要补位",
    "两个人应该同时抢同一个空当"
  ],
  "notes": "机器候选前两条直接覆盖轮转触发和中腰球分支；商品信息混杂的抓回头视频不列为必看。"
}
```

## AQ012 · 杀球落点应该如何选择

- 类型：`tactics`
- 预期模式：`text_primary`
- 来源：`answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [杀球瞄准 杀球瞄准 卢迦彧的杀球不是那种很重的，所以落点上就尤为重要，比赛中非常容易被防守反击!中间涉及到了张指导的肖像权，已经经过了前辈本人的同意!](https://www.douyin.com/video/7659348110628345210) (`7659348110628345210`)
- 必看候选: [双打进攻思路 抛砖引玉，场景太多，整体就是要根据自己和队友的位置去考虑](https://www.douyin.com/video/7619576226616745445) (`7619576226616745445`)

### 机器补充候选

- 机器候选: [大家可以去试一试，不过要确实有需求在折球哦，头像挡住观看落点的话，可以打开评论区观看😂](https://www.douyin.com/video/7069948509838904591) (`7069948509838904591`)
- 机器候选: [这样练球落点准，而且球头和追球的感觉很真实](https://www.douyin.com/video/7078117752275225891) (`7078117752275225891`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7659348110628345210"
  ],
  "required_video_ids": [
    "7659348110628345210",
    "7619576226616745445"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "没有脱离场景的唯一最佳落点；杀球不够重时优先追求更尖、更靠边和可衔接的回球。",
      "acceptable_terms": [
        "没有唯一",
        "更尖",
        "更靠边"
      ],
      "evidence_video_ids": [
        "7659348110628345210"
      ]
    },
    {
      "description": "头顶区或被拉开时要兼顾保护直线和自身回位距离，不能只看得分线路。",
      "acceptable_terms": [
        "保护直线",
        "回位距离",
        "头顶区"
      ],
      "evidence_video_ids": [
        "7659348110628345210"
      ]
    },
    {
      "description": "双打落点还要根据前场搭档覆盖与对手站位，在边线、中路和身体位间选择。",
      "acceptable_terms": [
        "前场搭档",
        "对手站位",
        "中路"
      ],
      "evidence_video_ids": [
        "7619576226616745445"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "需要区分单打或双打、快速突击或完整重杀以及自身位置。",
      "acceptable_terms": [
        "单打或双打",
        "快速突击",
        "自身位置"
      ]
    }
  ],
  "forbidden_claims": [
    "杀球永远应该杀直线",
    "杀球永远应该杀斜线",
    "选择落点不需要考虑回位"
  ],
  "notes": "使用落点主证据和双打站位证据，避免把某一线路写成通用答案。"
}
```

## AQ013 · 单打被动后场应该打直线还是斜线

- 类型：`tactics`
- 预期模式：`text_primary`
- 来源：`answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [被动位变线 这个位置是比较被动的，主动的在身前的，直接用小臂手腕就可以挡过去](https://www.douyin.com/video/7491780200468843833) (`7491780200468843833`)
- 必看候选: [被动高远 别说这样容易抡大臂，不这样偷出来时间抢架拍位置也是个输，真被动就没时间侧身，没时间架拍，没空间做正常架拍了，所以大家总说职业选手不架拍，其实架了，只不过没做那么主动的架拍罢了](https://www.douyin.com/video/7558912953539071292) (`7558912953539071292`)

### 机器补充候选

- 机器候选: [反手被动高远 虽然被动，但是放松发力更重要，别说示范的球不到位，也打出界一米了，主要是在底线摄像机放不下了](https://www.douyin.com/video/7546109410041908538) (`7546109410041908538`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7491780200468843833"
  ],
  "required_video_ids": [
    "7491780200468843833",
    "7558912953539071292"
  ],
  "irrelevant_video_ids": [
    "7123390328643603752"
  ],
  "required_text_points": [
    {
      "description": "被动且击球点已经落后时，优先选择与当前挥拍路径相容的安全直线或高质量过渡，不勉强改斜线。",
      "acceptable_terms": [
        "击球点落后",
        "安全直线",
        "不勉强斜线"
      ],
      "evidence_video_ids": [
        "7491780200468843833",
        "7558912953539071292"
      ]
    },
    {
      "description": "只有在仍有触球控制、拍面调整时间且对手站位值得利用时，才考虑主动改变斜线。",
      "acceptable_terms": [
        "触球控制",
        "拍面调整",
        "对手站位"
      ],
      "evidence_video_ids": [
        "7491780200468843833"
      ]
    },
    {
      "description": "线路选择必须同时保留下一拍回位和防守连接。",
      "acceptable_terms": [
        "下一拍",
        "回位",
        "防守连接"
      ],
      "evidence_video_ids": [
        "7558912953539071292"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "知识库没有一条直接完整比较单打被动直线与斜线的来源；结论是基于挥拍路径和被动处理证据的有限综合。",
      "acceptable_terms": [
        "没有直接比较",
        "有限综合",
        "被动处理"
      ]
    }
  ],
  "forbidden_claims": [
    "单打被动后场永远只能打直线",
    "单打被动后场永远应该打斜线",
    "双打两人站位规则可以直接证明单打线路"
  ],
  "notes": "排除实际讲双打两人站位的视频；保留单打线路相关证据并明确证据不完整。"
}
```

## AQ014 · 防守反击的战术思路是什么

- 类型：`tactics`
- 预期模式：`text_primary`
- 来源：`answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [单打防守反击](https://www.douyin.com/video/7602766054809333617) (`7602766054809333617`)
- 必看候选: [双打防守思路 你总会遇到你挑不起来的进攻](https://www.douyin.com/video/7621243051541587889) (`7621243051541587889`)
- 必看候选: [模拟的防守挡斜线随后抢网反击](https://www.douyin.com/video/7127470220309957923) (`7127470220309957923`)

### 机器补充候选

- 机器候选: [吊球和刹球要相互配合使用，拉扯对手防守的站位，一味的强攻很容易被防反](https://www.douyin.com/video/7115241358255803683) (`7115241358255803683`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7602766054809333617"
  ],
  "required_video_ids": [
    "7602766054809333617",
    "7621243051541587889",
    "7127470220309957923"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "防守反击先把对方进攻中和并提高回球质量，再寻找反攻机会。",
      "acceptable_terms": [
        "先中和",
        "回球质量",
        "反攻机会"
      ],
      "evidence_video_ids": [
        "7602766054809333617",
        "7621243051541587889"
      ]
    },
    {
      "description": "观察进攻者的移动方向、前场空当和击球节奏，再通过变线或节奏变化制造脱离。",
      "acceptable_terms": [
        "移动方向",
        "前场空当",
        "节奏变化"
      ],
      "evidence_video_ids": [
        "7602766054809333617"
      ]
    },
    {
      "description": "挡网后先观察对方下一拍，再突然加速，体现从防守到进攻的时机转换。",
      "acceptable_terms": [
        "先观察",
        "突然加速",
        "时机转换"
      ],
      "evidence_video_ids": [
        "7127470220309957923"
      ]
    },
    {
      "description": "单打重点是利用进攻者位移，双打还要同时读取前场队员和搭档位置。",
      "acceptable_terms": [
        "单打",
        "双打",
        "搭档位置"
      ],
      "evidence_video_ids": [
        "7602766054809333617",
        "7621243051541587889"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "反击强度受来球质量、接球高度和单双打阵型限制，不能每球都强行反攻。",
      "acceptable_terms": [
        "来球质量",
        "接球高度",
        "不能每球"
      ]
    }
  ],
  "forbidden_claims": [
    "防守球都应该立即反攻",
    "防守反击只需要改变线路",
    "双打防守时只看球不用看人"
  ],
  "notes": "将广义战术拆成中和、观察、变线和启动四步，并保留单双打差异。"
}
```

## AQ015 · 正手握拍应该怎么握

- 类型：`technical_action`
- 预期模式：`video_primary`
- 来源：`answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [正常击球位置的握拍，没有商量的，特殊位置有可能会握拍微调](https://www.douyin.com/video/7213191190382972172) (`7213191190382972172`)
- 必看候选: [半拳式握拍是发力必备的握拍，没有半拳式，基本出现不了鞭甩，因为大拇指会卡住](https://www.douyin.com/video/7086276287681137961) (`7086276287681137961`)
- 必看候选: [我知道很多人学不会握拍，是不知道虎口具体是哪里，这次你们会了吗？](https://www.douyin.com/video/7242877295336164642) (`7242877295336164642`)

### 机器补充候选

- 机器候选: [时间不够，太长了怕做不精细，第一集概念，第二集讲动作](https://www.douyin.com/video/7112628690395106560) (`7112628690395106560`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7213191190382972172"
  ],
  "required_video_ids": [
    "7213191190382972172",
    "7086276287681137961",
    "7242877295336164642"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "基础正手握拍采用半拳形态，掌心留空间，食指与其余手指分工而不是整手攥死。",
      "acceptable_terms": [
        "半拳",
        "掌心空间",
        "食指"
      ],
      "evidence_video_ids": [
        "7086276287681137961"
      ]
    },
    {
      "description": "虎口应参照拍框内侧而非简单正对拍框，使正常击球时能连接大臂和小臂。",
      "acceptable_terms": [
        "虎口",
        "拍框内侧",
        "大臂带动小臂"
      ],
      "evidence_video_ids": [
        "7213191190382972172",
        "7242877295336164642"
      ]
    },
    {
      "description": "准备握拍可向正手发力握拍转换，特殊位置再做小幅微调，不是一种角度覆盖所有击球。",
      "acceptable_terms": [
        "准备握拍",
        "发力握拍",
        "特殊位置"
      ],
      "evidence_video_ids": [
        "7213191190382972172",
        "7086276287681137961"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "虎口、手指和拍面的准确关系主要靠视频观察；手型、手胶粗细和击球位置会影响外观。",
      "acceptable_terms": [
        "视频观察",
        "手胶粗细",
        "击球位置"
      ]
    }
  ],
  "forbidden_claims": [
    "正手握拍从准备到结束都要用力攥紧",
    "虎口必须正对拍框中心",
    "一种握拍角度适用于所有击球位置"
  ],
  "notes": "三条视频分别覆盖正常角度、半拳发力和虎口定位；形态结论由用户反馈持续校正。"
}
```

## AQ016 · 拍面总是控制不住

- 类型：`diagnosis`
- 预期模式：`video_primary`
- 来源：`answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [握拍从准备握拍，向右旋转直至虎口对着正拍面，或接近正拍面](https://www.douyin.com/video/7146762792438074665) (`7146762792438074665`)
- 必看候选: [正常击球位置的握拍，没有商量的，特殊位置有可能会握拍微调](https://www.douyin.com/video/7213191190382972172) (`7213191190382972172`)

### 机器补充候选

- 机器候选: [承认被动，是一件很难的事](https://www.douyin.com/video/7174969770511551756) (`7174969770511551756`)
- 机器候选: [展搓 嗓子一直说不出话，如有吐字不清请配合字幕看，感谢谅解](https://www.douyin.com/video/7526124617461173562) (`7526124617461173562`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7146762792438074665"
  ],
  "required_video_ids": [
    "7146762792438074665",
    "7213191190382972172"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "先按正反手、主动被动、击球位置和出球错误方向拆分问题，不能把拍面失控视为单一故障。",
      "acceptable_terms": [
        "正反手",
        "主动被动",
        "击球位置"
      ],
      "evidence_video_ids": [
        "7146762792438074665",
        "7213191190382972172"
      ]
    },
    {
      "description": "拍面方向与握拍角度、虎口朝向和触球位置相互关联，必要时调整握拍而不是强扭手腕。",
      "acceptable_terms": [
        "握拍角度",
        "虎口朝向",
        "不扭手腕"
      ],
      "evidence_video_ids": [
        "7146762792438074665"
      ]
    },
    {
      "description": "正常击球和特殊被动位置允许不同程度的握拍微调。",
      "acceptable_terms": [
        "正常击球",
        "特殊位置",
        "握拍微调"
      ],
      "evidence_video_ids": [
        "7213191190382972172"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "没有具体击球种类和用户视频时只能给排查顺序，不能确认哪一个环节造成失控。",
      "acceptable_terms": [
        "排查顺序",
        "用户视频",
        "不能确认"
      ]
    }
  ],
  "forbidden_claims": [
    "把手腕锁死就一定能控制拍面",
    "所有击球都应该保持同一个拍面角度",
    "已经确定是握拍造成拍面失控"
  ],
  "notes": "将该题定义为不确定性诊断：给排查框架和通用握拍拍面关系，不做具体动作定论。"
}
```

## AQ017 · 杀球时手肘应该放在哪里

- 类型：`technical_action`
- 预期模式：`video_primary`
- 来源：`answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [发力的关键 架拍肘的摆动越小，出拍越快门槛也就越高，代价是力量会被削弱，肘的空间越充分，力量会更大，代价是出拍会相对慢，但是门槛低，业余的球友们肯定要从基础的低门槛开始](https://www.douyin.com/video/7458505857844776250) (`7458505857844776250`)
- 必看候选: [重杀框架 可以和期一起看，不同的框架可以决定不同的杀球](https://www.douyin.com/video/7659991105622862457) (`7659991105622862457`)

### 机器补充候选

- 机器候选: [杀球瞄准 杀球瞄准 卢迦彧的杀球不是那种很重的，所以落点上就尤为重要，比赛中非常容易被防守反击!中间涉及到了张指导的肖像权，已经经过了前辈本人的同意!](https://www.douyin.com/video/7659348110628345210) (`7659348110628345210`)
- 机器候选: [不用管身高，网带能卡住大臂就行在哪卡都可以，用网带辅助不依赖大臂挥下去](https://www.douyin.com/video/7322291358931127592) (`7322291358931127592`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7458505857844776250"
  ],
  "required_video_ids": [
    "7458505857844776250",
    "7659991105622862457"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "杀球时手肘没有一个对所有人和所有球速都固定的坐标；框架要在速度、力量和容错间取舍。",
      "acceptable_terms": [
        "没有固定",
        "速度和力量",
        "框架"
      ],
      "evidence_video_ids": [
        "7458505857844776250",
        "7659991105622862457"
      ]
    },
    {
      "description": "准备阶段要给肘和前臂留下展开空间，出拍时肘向前带动而不是提前锁死。",
      "acceptable_terms": [
        "展开空间",
        "肘向前",
        "不要锁死"
      ],
      "evidence_video_ids": [
        "7458505857844776250",
        "7659991105622862457"
      ]
    },
    {
      "description": "快速框架和重杀框架的肘部幅度不同，应按能力和击球目的选择。",
      "acceptable_terms": [
        "快速框架",
        "重杀框架",
        "击球目的"
      ],
      "evidence_video_ids": [
        "7458505857844776250",
        "7659991105622862457"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "精确肘高、肩肘拍相对位置和个人活动度需要视频观察；出现肩肘疼痛应停止相关动作。",
      "acceptable_terms": [
        "视频观察",
        "个人活动度",
        "疼痛"
      ]
    }
  ],
  "forbidden_claims": [
    "杀球时手肘越高越好",
    "所有杀球的手肘位置完全相同",
    "肩膀疼也要强行把肘顶到固定角度"
  ],
  "notes": "检索首屏多为杀球落点或反手，改用直接讲肘部框架和重杀框架的视频。"
}
```

## AQ018 · 正手高远球的击球姿势是什么样

- 类型：`technical_action`
- 预期模式：`video_primary`
- 来源：`answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [基础挥拍 可以当网课看了，@ 你不会挥拍的小伙伴来看吧](https://www.douyin.com/video/7453420876076240188) (`7453420876076240188`)
- 必看候选: [基础挥拍重快 由于要控制时长我剪辑的很精简，基础挥拍如何打的重，如何打的快，建议多看两边，详细的我们直播间来说](https://www.douyin.com/video/7383154379915906319) (`7383154379915906319`)
- 必看候选: [向前的挥拍，可以使挥拍的力最高效的发挥](https://www.douyin.com/video/7102635326803332393) (`7102635326803332393`)

### 机器补充候选

- 机器候选: [教科书动作教不出高手，但是实战动作可以](https://www.douyin.com/video/7098156298415459599) (`7098156298415459599`)
- 机器候选: [小孩子和球友正手位大距离位移打高远球，前交叉步的要求更高，后交叉容易，距离相近](https://www.douyin.com/video/7059205903639121187) (`7059205903639121187`)
- 机器候选: [现场嘈杂，说话声音大了点，各位见谅](https://www.douyin.com/video/7175339579392707878) (`7175339579392707878`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7453420876076240188"
  ],
  "required_video_ids": [
    "7453420876076240188",
    "7383154379915906319",
    "7102635326803332393"
  ],
  "irrelevant_video_ids": [
    "7541623926234811705",
    "7546109410041908538",
    "7558912953539071292"
  ],
  "required_text_points": [
    {
      "description": "正手高远球的基础挥拍由身体转动和腰腹带动，球拍从身后向前完成击球。",
      "acceptable_terms": [
        "身体转动",
        "腰腹带动",
        "从后向前"
      ],
      "evidence_video_ids": [
        "7453420876076240188",
        "7383154379915906319"
      ]
    },
    {
      "description": "手臂自然展开并在末段加速，避免直臂僵硬或只用大臂抡球。",
      "acceptable_terms": [
        "自然展开",
        "末段加速",
        "只用大臂"
      ],
      "evidence_video_ids": [
        "7453420876076240188",
        "7383154379915906319"
      ]
    },
    {
      "description": "挥拍路径应向前穿过击球区域并自然随挥，不用先向上再横着扫。",
      "acceptable_terms": [
        "向前挥拍",
        "自然随挥",
        "挥拍路径"
      ],
      "evidence_video_ids": [
        "7102635326803332393"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "击球点、侧身幅度、肘拍关系和连续节奏必须结合动作视频学习，文字不能完整呈现姿势。",
      "acceptable_terms": [
        "击球点",
        "动作视频",
        "文字不能完整"
      ]
    }
  ],
  "forbidden_claims": [
    "反手被动高远就是正手高远的标准姿势",
    "正手高远只需要伸直手臂抡球",
    "仅看文字就能确认完整击球姿势"
  ],
  "notes": "原机器候选全部是反手或被动高远，已排除并换成正常基础挥拍、身体传导和挥拍路径。"
}
```

## AQ019 · 网前搓球怎么控制拍面

- 类型：`technical_action`
- 预期模式：`video_primary`
- 来源：`answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [展搓 嗓子一直说不出话，如有吐字不清请配合字幕看，感谢谅解](https://www.douyin.com/video/7526124617461173562) (`7526124617461173562`)
- 必看候选: [滚网搓球 双打网前有人看守时有奇效](https://www.douyin.com/video/7509355373729762619) (`7509355373729762619`)
- 必看候选: [贴网球需要一定的抛物线，所以这样的高度不算高，有人守在网前就不要搓了](https://www.douyin.com/video/7144168689510649128) (`7144168689510649128`)

### 机器补充候选

- 机器候选: [正手网前步法 当然还要注意左手的摆放和重心的控制，但是时间有限，直播的时候讲吧](https://www.douyin.com/video/7406541084219821312) (`7406541084219821312`)
- 机器候选: [搓球的方向很重要，网前搓球第一集](https://www.douyin.com/video/7052148706681883907) (`7052148706681883907`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7526124617461173562"
  ],
  "required_video_ids": [
    "7526124617461173562",
    "7509355373729762619",
    "7144168689510649128"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "展搓时拍面尽量端平，以小幅向前动作触球；来球冲劲大时可轻微回撤卸力。",
      "acceptable_terms": [
        "拍面端平",
        "向前动作",
        "回撤卸力"
      ],
      "evidence_video_ids": [
        "7526124617461173562"
      ]
    },
    {
      "description": "滚搓或不同旋转方式会使用更倾斜或更打开的拍面和较小的向前力量，不能套同一角度。",
      "acceptable_terms": [
        "滚搓",
        "拍面倾斜",
        "向前力量"
      ],
      "evidence_video_ids": [
        "7509355373729762619"
      ]
    },
    {
      "description": "触球点在身体内侧、边线附近或不同高度时，拍面角度和包裹方向要随位置调整。",
      "acceptable_terms": [
        "触球点",
        "边线",
        "随位置调整"
      ],
      "evidence_video_ids": [
        "7144168689510649128"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "搓球拍面的动态角度和轨迹主要靠视频观察，来球速度与触球高度会改变处理。",
      "acceptable_terms": [
        "动态角度",
        "来球速度",
        "触球高度"
      ]
    }
  ],
  "forbidden_claims": [
    "所有搓球拍面永远保持水平",
    "手腕翻得越大搓球越转",
    "搓球拍面不受触球位置影响"
  ],
  "notes": "按展搓、滚搓和不同触球位置拆分证据；该题纳入问题理解与证据覆盖回归。"
}
```

## AQ020 · 被动后场来不及架拍如何调整

- 类型：`diagnosis`
- 预期模式：`balanced`
- 来源：`answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [被动高远 别说这样容易抡大臂，不这样偷出来时间抢架拍位置也是个输，真被动就没时间侧身，没时间架拍，没空间做正常架拍了，所以大家总说职业选手不架拍，其实架了，只不过没做那么主动的架拍罢了](https://www.douyin.com/video/7558912953539071292) (`7558912953539071292`)
- 必看候选: [后场框架应用 如果基础好，可以推荐出快速框架，之前发过很多爆发力出框架的作品！但是顶肘动作小带来效率的同时，也会因为顶肘动作小而削弱摆臂的幅度而失去力量！如果没有的专业力量的的朋友推荐第二种，但是要注意是拍低肘不低！不然会导致错误顶肘成为错误动作！ 总结，快速框架优点是容易做速度快效率高！缺点不好发力 动态低架优点是，容错率高，省力！缺点是不好学习 普通的架拍，优点是都能兼顾，缺点是该来不及的还是来不及](https://www.douyin.com/video/7589749293205363633) (`7589749293205363633`)
- 必看候选: [被动肯定要发力，但是要把力量使用在挥拍的速度上，而不是动作的幅度](https://www.douyin.com/video/7153445193713290511) (`7153445193713290511`)
- 必看候选: [反手被动高远 虽然被动，但是放松发力更重要，别说示范的球不到位，也打出界一米了，主要是在底线摄像机放不下了](https://www.douyin.com/video/7546109410041908538) (`7546109410041908538`)

### 机器补充候选

- 没有额外候选。

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7558912953539071292"
  ],
  "required_video_ids": [
    "7558912953539071292",
    "7589749293205363633",
    "7153445193713290511",
    "7546109410041908538"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "真正来不及时要把主动完整架拍降级成更短、更快的被动框架，不强求完整侧身。",
      "acceptable_terms": [
        "被动框架",
        "不强求侧身",
        "来不及"
      ],
      "evidence_video_ids": [
        "7558912953539071292",
        "7589749293205363633"
      ]
    },
    {
      "description": "尽量更早在可控位置向上击球；击球点落后时动作和收拍也随之调整。",
      "acceptable_terms": [
        "更早击球",
        "向上击球",
        "击球点落后"
      ],
      "evidence_video_ids": [
        "7558912953539071292"
      ]
    },
    {
      "description": "被动发力追求挥拍速度和连续传导，而不是把动作幅度做得更大。",
      "acceptable_terms": [
        "挥拍速度",
        "力量传导",
        "动作幅度"
      ],
      "evidence_video_ids": [
        "7153445193713290511"
      ]
    },
    {
      "description": "反手被动需要单独的握拍、触球和身体移动处理，不能与正手头顶合并成一个动作。",
      "acceptable_terms": [
        "反手被动",
        "正手头顶",
        "不能合并"
      ],
      "evidence_video_ids": [
        "7546109410041908538",
        "7558912953539071292"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "需要用户视频确认是判断慢、移动不到位、正手头顶还是反手被动，才能给出具体纠错。",
      "acceptable_terms": [
        "用户视频",
        "判断慢",
        "正手还是反手"
      ]
    }
  ],
  "forbidden_claims": [
    "来不及架拍时应该把动作做得更完整",
    "任何被动后场都必须侧身",
    "被动高远只需要甩手腕"
  ],
  "notes": "与 AQ001 形成不同问法的鲁棒性案例，共享证据但保留独立金标；纳入问题理解与证据覆盖回归。"
}
```

## AQ021 · 平抽挡怎样连续发力

- 类型：`technical_action`
- 预期模式：`balanced`
- 来源：`answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [抽球细节 面对快球，假设球一共飞行0.8秒到你的击球点，如果你光伸拍做框架就用了0.5秒，那就没法打了，但是如果0.3秒就能做好框架，你就有0.5秒可以挥拍](https://www.douyin.com/video/7560064232592493882) (`7560064232592493882`)
- 必看候选: [握拍微调 抽挡反手为主，尽量不做正反手转换](https://www.douyin.com/video/7447084061371272507) (`7447084061371272507`)
- 必看候选: [抽挡连贯 我知道有些兄弟很要强，受不了这种屈辱，就是不能承认被动，没关系，打羽毛球吧，它一定会教会你](https://www.douyin.com/video/7506736569824726332) (`7506736569824726332`)
- 必看候选: [高速对抗步法 小姐姐是两省冠军🏆，这种情况属于高速对抗状态下，就是球都比较平，没有侧身的时间和意义](https://www.douyin.com/video/7652440366436945017) (`7652440366436945017`)

### 机器补充候选

- 机器候选: [压抽才是双打的主旋律，没人一上来就挑给你](https://www.douyin.com/video/7205399670959459623) (`7205399670959459623`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7560064232592493882"
  ],
  "required_video_ids": [
    "7560064232592493882",
    "7447084061371272507",
    "7506736569824726332",
    "7652440366436945017"
  ],
  "irrelevant_video_ids": [
    "7589749293205363633"
  ],
  "required_text_points": [
    {
      "description": "连续发力来自快速还原和紧凑框架，让每拍都有出拍时间，而不是持续绷紧手臂。",
      "acceptable_terms": [
        "快速还原",
        "紧凑框架",
        "出拍时间"
      ],
      "evidence_video_ids": [
        "7560064232592493882"
      ]
    },
    {
      "description": "抽挡以反手握拍为主做小幅微调，减少大范围正反手切换造成的迟滞。",
      "acceptable_terms": [
        "反手握拍为主",
        "微调",
        "减少切换"
      ],
      "evidence_video_ids": [
        "7447084061371272507"
      ]
    },
    {
      "description": "被动时先保护身体位并把球回平，获得时间后再提高框架主动抽压。",
      "acceptable_terms": [
        "保护身体位",
        "回平",
        "提高框架"
      ],
      "evidence_video_ids": [
        "7506736569824726332"
      ]
    },
    {
      "description": "高速平球中保持正面和连续节奏，不为每一拍做完整侧身。",
      "acceptable_terms": [
        "高速平球",
        "保持正面",
        "连续节奏"
      ],
      "evidence_video_ids": [
        "7652440366436945017"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "主动抽压、被动挡球和不同触球高度的发力顺序不同，需要观看连续动作。",
      "acceptable_terms": [
        "主动抽压",
        "被动挡球",
        "触球高度"
      ]
    }
  ],
  "forbidden_claims": [
    "连续发力就是全程把手臂绷紧",
    "每拍都必须完整换成正手握拍",
    "平抽挡动作越大越容易连续"
  ],
  "notes": "检索原首位是通用放松架拍；改为抽球框架、握拍微调、被动连贯和高速步法四条直接证据，并纳入问题理解与证据覆盖回归。"
}
```

## AQ022 · 步法启动慢而且回动不及时

- 类型：`diagnosis`
- 预期模式：`balanced`
- 来源：`answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [其实接慢节奏，是很难找到启动点的](https://www.douyin.com/video/7158640349798255907) (`7158640349798255907`)
- 必看候选: [步法节奏 越着急跑输的越快，中场待着不动也不行，所以只能去找到这个接球的节奏](https://www.douyin.com/video/7571574635323124145) (`7571574635323124145`)
- 必看候选: [回动步法合理性 每个人的合理也不一样，有的人腿的力量强，并步能并很远，所以还要结合自己的情况](https://www.douyin.com/video/7643719807951615482) (`7643719807951615482`)
- 必看候选: [分解步法种类繁多，这是练启动有代表性的，一轮一口气做完，做3组。我肯定是没做到10秒钟，要不视频太长😓](https://www.douyin.com/video/7056244399390412064) (`7056244399390412064`)

### 机器补充候选

- 机器候选: [步法弹性 方法也很重要](https://www.douyin.com/video/7531326870298873147) (`7531326870298873147`)
- 机器候选: [1 白鞋白胶布2低重心步法回动3低重心步法训练，这是我自创训练](https://www.douyin.com/video/7085169366005714217) (`7085169366005714217`)
- 机器候选: [后场就是刻意练的被动步法，不是不积极，主要练回动的节奏感](https://www.douyin.com/video/7280727710740139264) (`7280727710740139264`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7158640349798255907"
  ],
  "required_video_ids": [
    "7158640349798255907",
    "7571574635323124145",
    "7643719807951615482",
    "7056244399390412064"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "把问题拆成击球后停顿、回位节奏、对手击球时机判断和纯移动能力四类，不先认定唯一原因。",
      "acceptable_terms": [
        "击球后停顿",
        "回位节奏",
        "时机判断"
      ],
      "evidence_video_ids": [
        "7158640349798255907",
        "7571574635323124145"
      ]
    },
    {
      "description": "击球后先稳定并及时回动，接近合理位置后放慢观察，在对手击球时再启动。",
      "acceptable_terms": [
        "及时回动",
        "放慢观察",
        "对手击球"
      ],
      "evidence_video_ids": [
        "7158640349798255907",
        "7571574635323124145"
      ]
    },
    {
      "description": "回位用并步还是交叉步应取决于距离、重心和个人能力，避免过多碎步。",
      "acceptable_terms": [
        "并步",
        "交叉步",
        "个人能力"
      ],
      "evidence_video_ids": [
        "7643719807951615482"
      ]
    },
    {
      "description": "练习可用低频大距离和高频小距离启动组合，并设置质量下降时的停止标准。",
      "acceptable_terms": [
        "低频",
        "高频",
        "停止标准"
      ],
      "evidence_video_ids": [
        "7056244399390412064"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "没有用户比赛视频无法判断主要瓶颈；单双打、场上位置和体能状态也会改变诊断。",
      "acceptable_terms": [
        "比赛视频",
        "单双打",
        "体能状态"
      ]
    }
  ],
  "forbidden_claims": [
    "启动慢唯一原因就是腿部力量差",
    "所有回位都应该使用交叉步",
    "只要增加训练量就一定能解决回动问题"
  ],
  "notes": "与 AQ006 区分为诊断题而非完整处方；增加多原因边界并纳入问题理解与证据覆盖回归。"
}
```

## AQ023 · 杀球动作怎么发力

- 类型：`technical_action`
- 预期模式：`balanced`
- 来源：`answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [00:00 / 00:47 后场发力下集，由下到上一步一步带动全身协调发力，发力为外旋，不会伤手腕，伤手腕说明没外旋](https://www.douyin.com/video/7052600326116887812) (`7052600326116887812`)
- 主证据候选: [不同杀球 给大家解释为什么每个运动员动作不一样，其实在我的视角里，都是脚蹬地开始发力传递到球拍，但是每个人有差异，比如有的胳膊有劲儿，有的腰腹有劲儿，有的手腕有劲儿，通过漫长的训练，无意识的找到最适合自己发力配比，所以大家学习也得根据自己情况来](https://www.douyin.com/video/7567155406117533051) (`7567155406117533051`)
- 必看候选: [发力第一集 大家没看懂就在看一遍，做辅助训练的时候小臂一定要特别放松](https://www.douyin.com/video/7484563688096091449) (`7484563688096091449`)
- 必看候选: [压球新讲 就算追求贴球发力，也得是建立在能把动作做完的基础上贴，怕打不到球也会本能的把球拍接近球而失去发力空间，这都是不对的](https://www.douyin.com/video/7440406891664133428) (`7440406891664133428`)

### 机器补充候选

- 机器候选: [反手杀球 不同的击球位置也会使用不同的动作,都有不同的效果](https://www.douyin.com/video/7550305145877155131) (`7550305145877155131`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7052600326116887812",
    "7567155406117533051"
  ],
  "required_video_ids": [
    "7052600326116887812",
    "7567155406117533051",
    "7484563688096091449",
    "7440406891664133428"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "杀球发力是从蹬地、腿髋、腰肩到肘、前臂和球拍的顺序传导，不是孤立甩手。",
      "acceptable_terms": [
        "脚蹬地",
        "腰带肩",
        "传到球拍"
      ],
      "evidence_video_ids": [
        "7052600326116887812",
        "7567155406117533051"
      ]
    },
    {
      "description": "前臂先保持放松，由大臂和肘带动后在末段加速，避免一开始就僵硬用力。",
      "acceptable_terms": [
        "前臂放松",
        "大臂带动小臂",
        "末段加速"
      ],
      "evidence_video_ids": [
        "7484563688096091449"
      ]
    },
    {
      "description": "架拍与球之间要有足够空间完成挥拍后半段，太贴球会丢失下压和发力空间。",
      "acceptable_terms": [
        "足够空间",
        "挥拍后半段",
        "发力空间"
      ],
      "evidence_video_ids": [
        "7440406891664133428"
      ]
    },
    {
      "description": "不同球员会按力量、协调和动作体系分配手指、手臂与身体用力，核心顺序相通但外形不必相同。",
      "acceptable_terms": [
        "发力配比",
        "核心顺序",
        "不必相同"
      ],
      "evidence_video_ids": [
        "7567155406117533051"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "快速突击、重杀、击球位置和个人能力不同，动作幅度与框架也不同；精确动作必须看视频。",
      "acceptable_terms": [
        "快速突击",
        "重杀",
        "看视频"
      ]
    },
    {
      "description": "出现肩肘腕疼痛时停止相关动作，视频中的技术表述不能替代医疗判断。",
      "acceptable_terms": [
        "疼痛",
        "停止",
        "医疗判断"
      ]
    }
  ],
  "forbidden_claims": [
    "杀球发力只靠手腕",
    "所有人的杀球动作应该完全一样",
    "动作幅度越大杀球越重",
    "外旋可以保证绝对不会受伤"
  ],
  "notes": "改用动力链、个体差异、肘带前臂和击球空间的直接证据；落点视频不再作为发力主证据。"
}
```

## AQ024 · 如何练习吊球和杀球衔接

- 类型：`training_plan`
- 预期模式：`balanced`
- 来源：`answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [吊球和刹球要相互配合使用，拉扯对手防守的站位，一味的强攻很容易被防反](https://www.douyin.com/video/7115241358255803683) (`7115241358255803683`)
- 必看候选: [软压还包括点杀，远网吊球等等](https://www.douyin.com/video/7093706918492917033) (`7093706918492917033`)
- 必看候选: [这属于为了下一拍更好衔接的步法，也是使用率最高的](https://www.douyin.com/video/7229889111706848544) (`7229889111706848544`)
- 必看候选: [杀球瞄准 杀球瞄准 卢迦彧的杀球不是那种很重的，所以落点上就尤为重要，比赛中非常容易被防守反击!中间涉及到了张指导的肖像权，已经经过了前辈本人的同意!](https://www.douyin.com/video/7659348110628345210) (`7659348110628345210`)

### 机器补充候选

- 没有额外候选。

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7115241358255803683"
  ],
  "required_video_ids": [
    "7115241358255803683",
    "7093706918492917033",
    "7229889111706848544",
    "7659348110628345210"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "训练目标是用相似准备动作在吊球、软压和杀球间做选择，拉扯站位而不是只练单次重杀。",
      "acceptable_terms": [
        "相似准备",
        "吊球和杀球",
        "拉扯站位"
      ],
      "evidence_video_ids": [
        "7115241358255803683",
        "7093706918492917033"
      ]
    },
    {
      "description": "位置不好时练习软压或远网吊球并连接下一拍，避免全力杀后脚下脱节。",
      "acceptable_terms": [
        "位置不好",
        "软压",
        "脚下脱节"
      ],
      "evidence_video_ids": [
        "7093706918492917033"
      ]
    },
    {
      "description": "加入击球后回位和上网衔接；具体步法随正手位、侧身程度和预期下一拍改变。",
      "acceptable_terms": [
        "击球后回位",
        "上网衔接",
        "下一拍"
      ],
      "evidence_video_ids": [
        "7229889111706848544",
        "7659348110628345210"
      ]
    },
    {
      "description": "给出按用户时长或默认15分钟分配的热身、同准备分解、二选一多球和自测，并附3天与2周进阶。",
      "acceptable_terms": [
        "15分钟",
        "3天修正",
        "2周巩固"
      ],
      "evidence_video_ids": [
        "7115241358255803683",
        "7093706918492917033",
        "7229889111706848544"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "计划需说明水平、单双打、独练或有喂球者等假设，并给无搭档时的可行替代。",
      "acceptable_terms": [
        "水平",
        "单双打",
        "独练"
      ]
    },
    {
      "description": "出现疼痛、连续失衡或动作质量下降时停止当前组或降低速度。",
      "acceptable_terms": [
        "疼痛",
        "失衡",
        "降低速度"
      ]
    }
  ],
  "forbidden_claims": [
    "吊杀衔接只需要反复全力杀球",
    "练两周保证完全掌握吊杀衔接",
    "杀球以后不需要考虑回位"
  ],
  "notes": "把战术原则转成符合练习处方模板的计划金标；具体技术与训练安排仍由用户反馈持续校正。"
}
```

## AQ025 · 双打接发战术和接发握拍应该怎么调整

- 类型：`technical_action`
- 预期模式：`balanced`
- 来源：`answer_modality_cases`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [双打发接发 永远考虑对手出球最快的位置，慢的位置球真来了再说](https://www.douyin.com/video/7501542236061420859) (`7501542236061420859`)
- 主证据候选: [接发准备 每个人都要清楚做动作的目的性，不能盲目学习](https://www.douyin.com/video/7639306481355832689) (`7639306481355832689`)
- 必看候选: [中低手位切腰](https://www.douyin.com/video/7591112983016940977) (`7591112983016940977`)
- 必看候选: [羽毛球握拍千变万化，随机应变，只是握拍，动作上面的后期会出](https://www.douyin.com/video/7053654124042194215) (`7053654124042194215`)
- 必看候选: [双打抓回头 紫电青霜不要去掉低胶，如果一定要去掉低胶，或者已经去掉底胶，就要考虑结合自己的能力，也要换掉拍头的连钉，普通的线孔就在盒子里赠送了的](https://www.douyin.com/video/7656927370758796145) (`7656927370758796145`)

### 机器补充候选

- 没有额外候选。

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7501542236061420859",
    "7639306481355832689"
  ],
  "required_video_ids": [
    "7501542236061420859",
    "7639306481355832689",
    "7591112983016940977",
    "7053654124042194215"
  ],
  "irrelevant_video_ids": [
    "7656927370758796145",
    "7086276287681137961"
  ],
  "required_text_points": [
    {
      "description": "战术上先准备对手最快能打出的线路，再根据停顿、持拍方向和节奏变化调整。",
      "acceptable_terms": [
        "最快的位置",
        "停顿",
        "节奏变化"
      ],
      "evidence_video_ids": [
        "7501542236061420859"
      ]
    },
    {
      "description": "接发准备要降低重心并让大小臂形成稳定紧凑关系，使球拍既能抢前点也能防偷后场。",
      "acceptable_terms": [
        "降低重心",
        "大小臂",
        "防偷球"
      ],
      "evidence_video_ids": [
        "7639306481355832689"
      ]
    },
    {
      "description": "按接球高度和来球质量选择推、放、切腰或先控制，不把接发策略写成单一扑球。",
      "acceptable_terms": [
        "接球高度",
        "推可以放",
        "切腰"
      ],
      "evidence_video_ids": [
        "7639306481355832689",
        "7591112983016940977"
      ]
    },
    {
      "description": "握拍应服务于当前触球位置和拍面方向，以可快速转换的准备握拍为基础做小幅调整。",
      "acceptable_terms": [
        "触球位置",
        "拍面方向",
        "握拍调整"
      ],
      "evidence_video_ids": [
        "7053654124042194215"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "接发策略和握拍会受发球方持拍手、站位、单双打规则与接发者水平影响；握拍形态需视频确认。",
      "acceptable_terms": [
        "持拍手",
        "站位",
        "视频确认"
      ]
    }
  ],
  "forbidden_claims": [
    "双打接发永远使用固定反手握拍不作调整",
    "接发时只需要考虑扑网",
    "正手重杀握拍就是双打接发握拍"
  ],
  "notes": "把复合问题拆成战术与握拍两部分；排除抓回头商品混杂视频和正手发力握拍，纳入问题理解与证据覆盖回归。"
}
```

## AQ026 · 我只描述杀球总下网，不给动作视频，能不能确定唯一原因

- 类型：`evidence_boundary`
- 预期模式：`balanced`
- 来源：`boundary_seed`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 暂无人工确认的视频标签。

### 机器补充候选

- 没有额外候选。

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [],
  "required_video_ids": [],
  "irrelevant_video_ids": [
    "7659348110628345210",
    "7506362888166083897"
  ],
  "required_text_points": [],
  "required_boundary_points": [
    {
      "description": "只知道杀球下网这一结果，不能确定唯一原因；击球点、拍面、挥拍路径、身体位置和来球都只是待验证假设。",
      "acceptable_terms": [
        "不能确定唯一原因",
        "击球点",
        "待验证假设"
      ]
    },
    {
      "description": "应要求正面或侧面动作视频、触球位置和具体场景，再把可能原因逐项排除。",
      "acceptable_terms": [
        "动作视频",
        "触球位置",
        "逐项排除"
      ]
    },
    {
      "description": "若列出可能原因，必须明确它们是排查方向而不是已经成立的诊断。",
      "acceptable_terms": [
        "排查方向",
        "不是诊断",
        "可能原因"
      ]
    }
  ],
  "forbidden_claims": [
    "唯一原因就是压腕不够",
    "已经可以确定你的杀球问题",
    "这条视频证明了下网的唯一原因"
  ],
  "notes": "按证据边界题审核通过：不设必看视频，不让泛化杀球视频承担个体诊断；击球空间视频可作为可选排查示例。"
}
```

## AQ027 · 练杀球以后肩膀疼，还能不能继续练

- 类型：`evidence_boundary`
- 预期模式：`text_primary`
- 来源：`boundary_seed`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 暂无人工确认的视频标签。

### 机器补充候选

- 没有额外候选。

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [],
  "required_video_ids": [],
  "irrelevant_video_ids": [
    "7288529711267859747",
    "7432633273060314408",
    "7453420876076240188"
  ],
  "required_text_points": [],
  "required_boundary_points": [
    {
      "description": "出现肩痛应停止引发疼痛的杀球和负重动作，不用训练量覆盖疼痛。",
      "acceptable_terms": [
        "停止",
        "疼痛动作",
        "不要继续练"
      ]
    },
    {
      "description": "持续、加重、夜间痛、明显无力或活动受限时，应由合格医生或物理治疗师评估。",
      "acceptable_terms": [
        "持续",
        "医生",
        "物理治疗师"
      ]
    },
    {
      "description": "Skill不能从文字诊断具体损伤，也不能用技术视频替代医疗评估。",
      "acceptable_terms": [
        "不能诊断",
        "医疗评估",
        "不能替代"
      ]
    }
  ],
  "forbidden_claims": [
    "肩膀疼也可以继续加量练杀球",
    "这一定是肩袖撕裂",
    "改完动作就一定能治好肩痛"
  ],
  "notes": "三个机器候选都不构成医疗安全证据，全部排除；本题只评估安全边界与转诊表述。"
}
```

## AQ028 · 刘辉羽毛球最推荐我买哪一支球拍

- 类型：`evidence_boundary`
- 预期模式：`text_primary`
- 来源：`boundary_seed`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [动作比较 大家需要根据能力选择球拍，而不同的重量的球拍，从动作的体现上会有区别，但是动作的本质都是一样的](https://www.douyin.com/video/7486058135547891004) (`7486058135547891004`)

### 机器补充候选

- 没有额外候选。

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7486058135547891004"
  ],
  "required_video_ids": [
    "7486058135547891004"
  ],
  "irrelevant_video_ids": [
    "7589749293205363633",
    "7231373527314631947"
  ],
  "required_text_points": [
    {
      "description": "知识库支持按个人能力、力量和适应程度选择球拍；不同重量会改变动作表现，但不存在人人同一答案。",
      "acceptable_terms": [
        "根据能力选择",
        "球拍重量",
        "不同表现"
      ],
      "evidence_video_ids": [
        "7486058135547891004"
      ]
    },
    {
      "description": "给建议前至少询问水平、单打或双打、力量与伤病、预算和已有球拍体验。",
      "acceptable_terms": [
        "水平",
        "预算",
        "已有球拍"
      ],
      "evidence_video_ids": [
        "7486058135547891004"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "现有证据没有刘辉对某一具体型号的通用或最新购买背书，不能冒充其个人推荐。",
      "acceptable_terms": [
        "没有具体型号",
        "不能冒充",
        "个人推荐"
      ]
    },
    {
      "description": "球拍价格、在售型号和个人适配会变化，回答不应虚构当前产品信息。",
      "acceptable_terms": [
        "在售型号",
        "会变化",
        "不能虚构"
      ]
    }
  ],
  "forbidden_claims": [
    "刘辉最推荐所有人购买同一支球拍",
    "这是刘辉本人给你的购买背书",
    "购买这个型号一定最适合你"
  ],
  "notes": "保留唯一直接讲按能力选拍的视频；后场框架和勾球视频仅因词面含球拍而召回，已排除。"
}
```

## AQ029 · 你给出的训练建议是不是刘辉本人认可的

- 类型：`evidence_boundary`
- 预期模式：`text_primary`
- 来源：`boundary_seed`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 暂无人工确认的视频标签。

### 机器补充候选

- 没有额外候选。

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [],
  "required_video_ids": [],
  "irrelevant_video_ids": [
    "7085169366005714217",
    "7541623926234811705",
    "7432633273060314408"
  ],
  "required_text_points": [],
  "required_boundary_points": [
    {
      "description": "答案和训练计划是 Skill 基于刘辉公开视频证据及项目规则生成的综合，不代表刘辉本人逐条审阅。",
      "acceptable_terms": [
        "Skill",
        "综合",
        "没有逐条审阅"
      ]
    },
    {
      "description": "必须区分视频中的原始教学、由多条证据归纳的结论和模型生成的练习安排。",
      "acceptable_terms": [
        "原始教学",
        "归纳",
        "生成的练习"
      ]
    },
    {
      "description": "不得冒充刘辉，也不得声称获得其授权、认可或个人背书。",
      "acceptable_terms": [
        "不得冒充",
        "没有授权",
        "个人背书"
      ]
    }
  ],
  "forbidden_claims": [
    "我是刘辉本人",
    "这些训练建议都经过刘辉本人认可",
    "刘辉已经逐条审核并授权这份答案"
  ],
  "notes": "纯来源与身份边界题；机器候选均不能证明个人认可，全部排除。"
}
```

## AQ030 · 只看文字说明，能不能确认我的正手握拍完全正确

- 类型：`evidence_boundary`
- 预期模式：`video_primary`
- 来源：`boundary_seed`
- 当前状态：`maintainer_reviewed`
- 自动回归资格：已有

### 已有视频标签

- 主证据候选: [半拳式握拍是发力必备的握拍，没有半拳式，基本出现不了鞭甩，因为大拇指会卡住](https://www.douyin.com/video/7086276287681137961) (`7086276287681137961`)
- 必看候选: [正常击球位置的握拍，没有商量的，特殊位置有可能会握拍微调](https://www.douyin.com/video/7213191190382972172) (`7213191190382972172`)
- 必看候选: [我知道很多人学不会握拍，是不知道虎口具体是哪里，这次你们会了吗？](https://www.douyin.com/video/7242877295336164642) (`7242877295336164642`)

### 机器补充候选

- 机器候选: [双打抓回头 紫电青霜不要去掉低胶，如果一定要去掉低胶，或者已经去掉底胶，就要考虑结合自己的能力，也要换掉拍头的连钉，普通的线孔就在盒子里赠送了的](https://www.douyin.com/video/7656927370758796145) (`7656927370758796145`)

### Review notes

请只编辑下面 JSON 中的值；视频填写 18-20 位 ID，日期使用 `YYYY-MM-DD`。

```json
{
  "maintainer_decision": "approved",
  "maintainer_reviewer": "Codex evidence review",
  "maintainer_reviewed_at": "2026-07-17",
  "primary_video_ids": [
    "7086276287681137961"
  ],
  "required_video_ids": [
    "7086276287681137961",
    "7213191190382972172",
    "7242877295336164642"
  ],
  "irrelevant_video_ids": [],
  "required_text_points": [
    {
      "description": "文字可以给出半拳、虎口、食指分工和掌心留空等检查点，但这些只是自查线索。",
      "acceptable_terms": [
        "半拳",
        "虎口",
        "食指"
      ],
      "evidence_video_ids": [
        "7086276287681137961",
        "7242877295336164642"
      ]
    },
    {
      "description": "正常击球握拍与特殊被动位置会有微调，不能用一张静态文字规则覆盖全部场景。",
      "acceptable_terms": [
        "正常击球",
        "特殊位置",
        "握拍微调"
      ],
      "evidence_video_ids": [
        "7213191190382972172"
      ]
    }
  ],
  "required_boundary_points": [
    {
      "description": "仅看文字不能确认握拍完全正确；至少需要清晰手部与拍面照片或视频，并说明击球场景。",
      "acceptable_terms": [
        "不能确认",
        "照片或视频",
        "击球场景"
      ]
    },
    {
      "description": "即使外观接近，也还要观察握拍压力、转换和实际出球，不能据此作百分之百判断。",
      "acceptable_terms": [
        "握拍压力",
        "实际出球",
        "百分之百"
      ]
    }
  ],
  "forbidden_claims": [
    "只看文字就能确认你的握拍完全正确",
    "一种静态握拍适合所有击球",
    "没有照片视频也可以百分之百判断"
  ],
  "notes": "将三条基础握拍视频作为自查材料，但把完全确认明确留在视觉证据边界之外。"
}
```
