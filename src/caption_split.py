# -*- coding: utf-8 -*-
"""
한국어 자막을 '의미 단위'로 끊는다.

글자수만 보고 기계적으로 끊으면 수식어와 피수식어가 갈라진다:
    우선 ChatGPT로 접속하셔서 좌측 / 사이드바를 열어줍니다.   (X)
    우선 ChatGPT로 접속하셔서 / 좌측 사이드바를 열어줍니다.   (O)

말 사이 간격으로 찾으면 되지 않느냐 하면, 안 된다.
Whisper 는 한 세그먼트 안에서 단어 타임스탬프를 빈틈없이 이어 붙이기 때문에
실제로는 끊어 말한 자리도 간격이 0.00초로 나온다. 그래서 **어미와 조사**로
끊을 자리를 판단한다.

끊기 좋은 자리(점수 높음):
    문장부호 > 절 끝 쉼표 > 연결어미(-아서/-고/-며/-지만…) > 때·뒤·동안 > 주제어(-은/-는)
    > 부사격 조사(-에/-에서/-으로…) > 주격·목적격 조사(-이/-가/-을/-를)
끊으면 안 되는 자리(점수 0, 거의 금지):
    꾸미는 말 뒤(「좌측」 사이드바, 「선명한」 파랑, 「하는」 학생)
    매인이름씨 앞(「쓸 / 수 있는」, 「할 / 것이」), 보조 용언 앞(「주고 / 있습니다」)
    수와 단위 사이(「여섯 / 자리」)

2026-10-07: 앞에서부터 한 줄씩 채우던 방식을 문장 전체를 보고 끊는 자리 조합을 고르는 방식(DP)으로 바꿨다.
「디드 시작하기」 영상(lecture-video-factory build-start.mjs)에서 사용자 자막 규칙에 맞춰 다듬은 것을 옮겼다.
    - 쉼표: 목록(「크레용, 사인펜, 색연필」) 사이는 낮게, 절 끝(「그리고,」「굵게,」)은 높게
    - 줄 비용 = 줄마다 20 + 끊는 자리 (100 - 점수) + 길이 벌점. 점수 0 자리는 300(거의 안 고름)
    - 한 줄은 max_chars 안팎, hard 넘으면 금지. 줄 길이를 고르게(max_chars 의 2/3 근처)
"""
import re

INF = float("inf")
ENDS = ("다.", "요.", "까?", "죠.", "!", "…", ".", "?")
CONNECTIVE = (   # 연결어미 — 절이 끝나는 자리
    "서", "면서", "지만", "는데", "은데", "니까", "으니",
    "아서", "어서", "여서", "셔서", "라서", "해서", "돼서", "봐서",
    "도록", "거나", "든지", "다면", "라면", "려면", "면", "고", "며",
    "자", "듯이", "듯", "게", "러", "고서", "하고",
)
ADVERBIAL = (    # 부사격 조사 — 여기서 끊으면 자연스럽다
    "에서", "에게", "한테", "으로", "까지", "부터", "처럼", "보다", "중에",
    "위해", "대해", "통해", "따라", "관해", "라고", "와", "과", "에", "로",
)
CASE = ("은", "는", "이", "가", "을", "를", "도", "만", "의")

# 이런 말 뒤에서 끊으면 어색하다 (뒤 낱말을 꾸미는 말)
MODIFIER = {
    "이", "그", "저", "이런", "그런", "저런", "각", "각각", "새", "첫",
    "두", "세", "네", "여러", "모든", "전체", "일부", "다음", "이전",
    "좌측", "우측", "상단", "하단", "왼쪽", "오른쪽", "위", "아래",
    "해당", "본", "동일한", "같은", "다른", "특정", "주요", "실제",
    "수백", "수십", "한", "내", "맨", "바로", "우리",
}
# 뒤 낱말을 꾸미는 끝(「하는 학생」「개발한 플랫폼」「쉬운 도안」「할 일」)
ADNOMINAL = re.compile(r"(?:[하되있없리쓰보주오가나르우키기지추]는|[한든온른린눈던운딘쉰]|할|쓸|볼|줄)$")
BOUND_NEXT = re.compile(r"^(수|것|것이|것을|것은|줄|뿐|만큼|따름|듯)$")
AUX_NEXT = re.compile(r"^(계신|계시|있는|있습|있어|주는|주세|줍니|보는|봅니|두는|둡니|놓|보일|두고|드리)")
PRONOUN_SUBJ = re.compile(r"^(제가|내가|우리가|저는|나는|우리는)$")
COUNTER_NEXT = re.compile(r"^(장|개|명|칸|초|분|번|가지|자리|점)")
NUMERAL_END = re.compile(r"([0-9]|하나|둘|셋|넷|여섯|여덟|백|천|두|세|네)$")


def _core(w):
    return re.sub(r"[^\w가-힣]+$", "", (w or "").strip())


def strip_end(t):
    """줄 끝 쉼표·마침표를 뗀다(자막 규칙 2·3). 물음표·느낌표는 둔다"""
    return re.sub(r"[\s,.。、…]+$", "", t).strip()


def break_score(word, nxt=None, prev=None, prev2=None):
    """이 낱말 뒤에서 줄을 바꿔도 되는 정도(0~100). nxt·prev·prev2 는 뒤 낱말·앞 낱말 둘"""
    w = (word or "").strip()
    if not w:
        return 0
    if w.endswith(ENDS):
        return 100
    if w.endswith(","):
        # 앞뒤 두 낱말 안에 쉼표가 또 있으면 목록. 맨 명사 뒤 쉼표(「손가락, 펜으로」)도 목록.
        # 다만 -게 로 끝난 절(「빠르게 그으면 굵게, 천천히 …」) 뒤 쉼표는 절 끝이다
        if any(x and x.strip().endswith(",") for x in (prev, prev2, nxt)):
            return 30
        base = break_score(w[:-1], nxt, prev, prev2)
        return 30 if base <= 20 and not _core(w[:-1]).endswith("게") else 92
    core = _core(w)
    nc = _core(nxt) if nxt else ""
    if core in MODIFIER:
        return 0
    if nxt and BOUND_NEXT.match(nc):
        return 0
    if PRONOUN_SUBJ.match(core):
        return 5
    if nxt and AUX_NEXT.match(nxt.strip()):
        return 0
    if core.endswith("의"):
        return 5
    if re.search(r"(화면|장면|정면|측면|표면|어떻게|이렇게|그렇게|저렇게)$", core):
        return 5
    if nxt and COUNTER_NEXT.match(nxt.strip()) and NUMERAL_END.search(core):
        return 0
    if ADNOMINAL.search(core):
        return 0
    if re.search(r"(뒤|후|때|동안|사이|가운데)$", core):
        sc = 70
    elif core.endswith("않게"):
        sc = 70
    elif re.search(r"(에서|에게|한테|으로|까지|부터|처럼|보다)$", core):
        sc = 50   # 「메뉴에서」를 연결어미 -서 로 읽지 않게 조사를 먼저 본다
    elif core.endswith("게"):
        sc = 5    # -게 부사·사동(「크게 보면서」)은 뒤 말과 붙인다
    elif core.endswith(CONNECTIVE):
        sc = 85
    elif re.search(r"[은는]$", core):
        sc = 60   # 주제어 뒤
    elif re.search(r"(이나|나)$", core):
        sc = 55
    elif core.endswith(ADVERBIAL):
        sc = 50
    elif core.endswith(CASE):
        sc = 40
    else:
        sc = 5
    # 조사로 끝난 말 바로 뒤가 꾸미는 말이면 그 꾸밈 절을 가르는 것이라 낮춘다(「선생님이 / 추천한 그림」)
    if sc <= 60 and nxt and ADNOMINAL.search(nc):
        sc = min(sc, 40)
    # 목록 가운데의 -과/-와/-나(「빨강, 노랑, 파랑과 / 하양, 검정」)
    if nxt and nxt.strip().endswith(",") and re.search(r"(과|와|나|이나|랑)$", core):
        sc = min(sc, 20)
    return sc


def split_words(words, max_chars=20, min_chars=6, hard=None, locked=None):
    """낱말 리스트 -> 의미 단위로 끊은 줄들(낱말 인덱스 구간 목록)

    words: 문자열 리스트(한 문장 또는 한 토막)
    max_chars: 한 줄 글자 수 기준(공백 포함, 줄 끝 쉼표·마침표 뺀 길이)
    hard: 넘으면 안 되는 길이(기본 max_chars + 2)
    locked: 끊으면 안 되는 낱말 인덱스(그 낱말 뒤). 화면 단추 이름처럼 한 덩어리로 둘 것
    반환: [(시작index, 끝index+1), ...]
    """
    n = len(words)
    if n == 0:
        return []
    hard = max_chars + 2 if hard is None else hard
    locked = locked or set()

    def length(i, j):
        return len(strip_end(" ".join(words[i:j])))

    if length(0, n) <= max_chars:
        return [(0, n)]
    ideal = round(max_chars * 2 / 3)

    def inner_comma(i, j):
        c = 0
        for k in range(i, j - 1):
            if words[k].strip().endswith(","):
                around = [words[k - 1] if k >= 1 else None, words[k - 2] if k >= 2 else None, words[k + 1] if k + 1 < n else None]
                if not any(x and x.strip().endswith(",") for x in around):
                    c += 1
        return c

    def piece_cost(i, j):
        L = length(i, j)
        if L > hard and j - i > 1:
            return INF
        short = max(0, min_chars - L) * 10 if j - i < n else 0
        return 20 + max(0, L - max_chars) * 10 + short + abs(L - ideal) * 0.5 + inner_comma(i, j) * 40

    best = [INF] * (n + 1)
    frm = [-1] * (n + 1)
    best[0] = 0
    for j in range(1, n + 1):
        for i in range(j):
            if best[i] == INF:
                continue
            if i > 0 and (i - 1) in locked:
                continue
            if i > 0:
                sc0 = break_score(words[i - 1], words[i], words[i - 2] if i >= 2 else None, words[i - 3] if i >= 3 else None)
                brk = 300 if sc0 <= 0 else 100 - sc0
            else:
                brk = 0
            c = best[i] + brk + piece_cost(i, j)
            if c < best[j]:
                best[j], frm[j] = c, i
    if best[n] == INF:
        return [(0, n)]
    out, j = [], n
    while j > 0:
        out.append((frm[j], j))
        j = frm[j]
    return out[::-1]


if __name__ == "__main__":
    tests = [
        "우선 ChatGPT로 접속하셔서 좌측 사이드바를 열어줍니다.",
        "그리고 사이드바 메뉴 중에 프로젝트 메뉴를 클릭해줍니다.",
        "동화책 한 권에는 삽화가 여러 장 들어가는데 이 삽화들의 일관성을 잡아주는 것이 오늘 만들 기준 이미지입니다.",
        "AI 이미지 생성의 원리를 이해하고 작업에 맞는 도구를 고를 수 있다.",
        "크레용은 빠르게 그으면 굵게, 천천히 그으면 가늘게 칠해집니다.",
        "삼원색으로 정하면 학생은 빨강, 노랑, 파랑과 하양, 검정만으로 필요한 색을 섞어 만들며 색의 혼합을 익힙니다.",
    ]
    for t in tests:
        ws = t.split()
        print(f"\n원문: {t}")
        for a, b in split_words(ws, max_chars=24):
            print("   |", strip_end(" ".join(ws[a:b])))
