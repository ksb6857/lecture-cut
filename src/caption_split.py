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
    문장부호 > 연결어미(-아서/-고/-며/-지만…) > 부사격 조사(-에/-에서/-으로…)
    > 주격·목적격 조사(-은/-는/-이/-가/-을/-를)
끊으면 안 되는 자리:
    조사 없는 맨 명사 뒤 (대개 뒤 명사를 꾸미는 관형어다: '좌측' 사이드바)
"""
import re

# 뒤에서부터 검사하므로 긴 것을 먼저 둔다
SENTENCE_END = ("다.", "요.", "까?", "죠.", "!", "…", ".", "?", "!")
COMMA = (",",)
CONNECTIVE = (   # 연결어미 — 절이 끝나는 자리
    "면서", "지만", "는데", "은데", "니까", "으니",
    "아서", "어서", "여서", "셔서", "라서", "해서", "돼서", "봐서",
    "도록", "거나", "든지", "다면", "라면", "려면", "면", "고", "며",
    "자", "듯이", "듯", "게", "러", "고서", "하고",
)
ADVERBIAL = (    # 부사격 조사 — 여기서 끊으면 자연스럽다
    "에서", "에게", "한테", "으로", "까지", "부터", "처럼", "보다", "중에",
    "위해", "대해", "통해", "따라", "관해", "라고", "와", "과", "에", "로",
)
CASE = ("은", "는", "이", "가", "을", "를", "도", "만", "의")

SCORE_SENTENCE, SCORE_COMMA = 100, 90
SCORE_CONNECTIVE, SCORE_ADVERBIAL, SCORE_CASE, SCORE_BARE = 80, 60, 40, 5

# 이런 말 뒤에서 끊으면 어색하다 (뒤 낱말을 꾸미는 말)
MODIFIER = {
    "이", "그", "저", "이런", "그런", "저런", "각", "각각", "새", "첫",
    "두", "세", "네", "여러", "모든", "전체", "일부", "다음", "이전",
    "좌측", "우측", "상단", "하단", "왼쪽", "오른쪽", "위", "아래",
    "해당", "본", "동일한", "같은", "다른", "특정", "주요", "실제",
}


def break_score(word: str) -> int:
    """이 낱말 뒤에서 줄을 바꿔도 되는 정도"""
    w = word.strip()
    if not w:
        return 0
    if w.endswith(SENTENCE_END):
        return SCORE_SENTENCE
    if w.endswith(COMMA):
        return SCORE_COMMA
    core = re.sub(r"[^\w가-힣]+$", "", w)      # 끝의 문장부호 제거
    if core in MODIFIER:
        return 0                               # 관형어 뒤는 끊지 않는다
    if core.endswith(CONNECTIVE):
        return SCORE_CONNECTIVE
    if core.endswith(ADVERBIAL):
        return SCORE_ADVERBIAL
    if core.endswith(CASE):
        return SCORE_CASE
    return SCORE_BARE


def split_words(words, max_chars=20, min_chars=6):
    """낱말 리스트 -> 의미 단위로 끊은 줄들(낱말 인덱스 구간 목록)

    words: 문자열 리스트
    반환: [(시작index, 끝index+1), ...]
    """
    n = len(words)
    if n == 0:
        return []
    lines, start = [], 0
    while start < n:
        # 남은 게 한 줄에 들어가면 끝
        if sum(len(words[i]) + 1 for i in range(start, n)) - 1 <= max_chars:
            lines.append((start, n))
            break

        best_i, best_val = None, -1
        length = 0
        for i in range(start, n):
            length += len(words[i]) + (1 if i > start else 0)
            if length > max_chars:
                break
            if length < min_chars and i + 1 < n:
                continue
            sc = break_score(words[i])
            # 같은 점수면 max_chars 에 가까운 쪽(줄을 꽉 채우는 쪽)을 택한다
            val = sc * 1000 + length
            if val > best_val:
                best_val, best_i = val, i

        if best_i is None:                     # 한 낱말이 너무 길 때
            best_i = start
        lines.append((start, best_i + 1))
        start = best_i + 1
    return lines


if __name__ == "__main__":
    tests = [
        "우선 ChatGPT로 접속하셔서 좌측 사이드바를 열어줍니다.",
        "그리고 사이드바 메뉴 중에 프로젝트 메뉴를 클릭해줍니다.",
        "동화책 한 권에는 삽화가 여러 장 들어가는데 이 삽화들의 일관성을 잡아주는 것이 오늘 만들 기준 이미지입니다.",
        "AI 이미지 생성의 원리를 이해하고 작업에 맞는 도구를 고를 수 있다.",
    ]
    for t in tests:
        ws = t.split()
        print(f"\n원문: {t}")
        for a, b in split_words(ws):
            print("   |", " ".join(ws[a:b]))
