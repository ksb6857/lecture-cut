# -*- coding: utf-8 -*-
"""
speech.json(VAD) + words.json + retakes.json -> keep_ranges.json

컷 경계는 **자막이 아니라 파형(VAD)** 에서 가져온다.
브루 같은 STT 의 단어 타임스탬프는 앞뒤로 0.3초씩 헐렁하고, 놓친 발화를
무음처럼 보이게 만들어 멀쩡한 말을 자르는 사고를 낸다.

규칙:
- VAD 가 찾은 발화 구간은 절대 중간에서 자르지 않는다 (말 잘림 원천 차단)
- **모든 무음을 max_silence 로 '깎는다'**. 그보다 짧은 쉼은 손대지 않는다.
- 재발화(retake) 삭제는 '해당 발화 구간의 절반 이상이 삭제 범위에 걸리면
  그 구간을 통째로 제거' 하는 방식 → 단어 단위로 쪼개다 말이 잘리는 일이 없다

max_silence 1.2초의 근거 (강의 영상 기준):
- 말의 자연스러움은 문장 내 0.6초, 문장 간 0.6~1.2초 쉼에서 가장 높게 평가된다.
  쉼표 뒤 실제 쉼은 0.38~0.67초, 마침표 뒤는 0.81~1.24초로 약 1:2 비율.
  (Frontiers in Psychology, 2022)
- 절(clause) 경계의 쉼은 단어 인지 속도와 명제 회상률을 높인다. 즉 강의에서
  문장 사이 쉼은 '버릴 공백'이 아니라 이해를 돕는 장치다.
- 인지부하 이론: 교육 영상은 학습자가 정보를 통합할 처리 시간이 필요하다.
  빠른 페이스는 작업기억의 처리를 방해한다.
- 실무 통념: 자동 컷이 어색해지는 주된 원인은 '덜 자른 것'이 아니라
  '너무 바짝 자른 것'이다. (auto-editor 기본 마진 0.2초도 같은 이유)
따라서 1.2초 이하의 쉼은 전부 원본 그대로 두고, 그보다 긴 침묵만 1.2초로
깎는다. 실측상 1.2초 이하 쉼은 다 합쳐도 3분대라 길이에 거의 영향이 없다.
"""
import bisect
import json
import sys
from pathlib import Path

PARAMS = {
    # 문장이 안 끝났는데 생긴 쉼 — 짧게. 뚝뚝 끊기는 느낌의 주범이다.
    # 0.60 -> 0.45 -> 0.20 으로 내려왔다. 근거는 아래 주석.
    "max_silence_mid": 0.20,
    # 문장이 끝난 자리의 쉼 — 문장 중간보다는 길어야 문단이 구분된다.
    # 0.80 -> 0.60 -> 0.70 (4차/5차 학습). 근거는 아래 주석.
    "max_silence_end": 0.70,
    # 장면이 바뀌는 컷 — 여기엔 0.47초짜리 장면전환(B 페이드)이 들어간다.
    # 쉼이 짧으면 페이드가 말 위에 겹쳐 뭉개진다. 사용자도 손으로 넣을 때
    # 이 자리의 무음을 일부러 늘렸다.
    "max_silence_scene": 1.20,
    "tail_ratio": 0.45,     # 남은 쉼을 앞말 뒤:뒷말 앞 = 45:55 로 나눈다
    # 뒷말 앞에 최소한 이만큼은 남긴다. VAD 는 발화 시작을 늦게 잡는다.
    # 실측(110분 강의 767구간): VAD 가 표시한 시작보다 먼저 소리가 올라온
    # 시간이 90분위 95ms, 95분위 135ms 였다. 앞을 110ms 만 남기면 7% 에서
    # 첫소리가 잘린다. 반대로 발화 끝 뒤에 남은 소리는 99분위가 8ms 라
    # 뒤를 길게 남길 이유가 없다. 앞뒤 배분을 앞쪽으로 옮긴다.
    # **쉼 전체 길이는 그대로다.** 같은 쉼 안에서 자리만 바뀐다.
    "min_lead": 0.15,
    "min_tail": 0.04,       # 그래도 말끝이 딱 붙어 끝나지는 않게
    "min_saving": 0.15,     # 이만큼도 못 줄이면 자르지 않음 (잔컷 방지)
    "start_lead": 0.30,     # 영상 맨 앞 여유
    "end_tail": 0.80,       # 맨 뒤 여유
    "delete_overlap": 0.5,  # 발화 구간이 삭제범위에 이만큼 걸치면 통째 제거
}
MIN_SEGMENT = 0.05      # 이보다 짧은 VAD 구간은 발화로 보지 않는다
# 위 값은 사람이 직접 손본 편집본(2차시 앞 2분, 컷 23곳)에서 역산했다.
#   문장 중간 : 중앙값 0.60초 (범위 0.23~0.80)
#   문장 끝   : 중앙값 0.80초 (범위 0.53~1.20)
#   tail/lead : 문장끝 0.37/0.47 → 뒤보다 앞을 조금 더 남긴다
# 문장부호로 구분하지 않고 전부 1.2초를 주면 문장 안에서 말이 뚝뚝 끊긴다.
# 이 값들은 낭독 연구의 쉼표(0.38~0.67초)/마침표(0.81~1.24초) 범위와도 맞는다.
#
# [2차 학습] 0.60/0.80 적용본을 사용자가 14분까지 다시 손봤다. 그 결과:
#   문장 중간 컷 95곳 중 22곳을 손댔고, 17곳을 더 짧게(중앙 0.33초) 줄였다.
#   문장 끝 컷 115곳 중 20곳을 손댔고(중앙 0.57초), "문장 끝 쉼은 자연스럽다"고
#   명시했으므로 0.80 은 유지한다.
# 문장 중간은 손댄 것의 중앙(0.33)과 그대로 둔 다수(0.60) 사이인 0.45 로 잡았다.
#
# [3차 학습] 0.45 적용본(2차시 v3)을 사용자가 끝까지 손봤다. 문장 중간
# 쉼에서 0.16~0.67초(중앙 0.24초)를 더 깎아낸 곳이 58곳, 합계 16.0초다.
# 자동편집이 남긴 0.45 를 사람이 계속 반으로 깎고 있다는 뜻이라 0.20 으로
# 내렸다. 사용자 지시: "말 중간의 쉼은 기니까 지루하다. 절반으로."
# 문장 끝 0.80 은 그대로 둔다 — 문단 구분이 사라지면 안 되고, 2차 학습에서
# 사용자가 "문장 끝 쉼은 자연스럽다"고 명시했다.
#
# [4차 학습] 문장 중간을 0.20 으로 내린 3차시 v4 를 사용자가 보고 "조금 긴
# 느낌" 이라고 했다. 편집본에서 실제로 들리는 쉼을 전부 재보니 원인이
# 문장 중간이 아니었다:
#   문장 중간 377곳  중앙 0.20초  최대 0.30초   합계 1.3분
#   문장 끝   230곳  중앙 0.80초  최대 0.90초   합계 3.0분  <- 전체 쉼의 70%
# 문장 중간은 이미 상한에 붙어 있어 더 깎을 게 없었고, 길이는 문장 끝에
# 몰려 있었다. 그래서 문장 끝만 0.60 으로 내렸다(약 46초 단축).
# 여기서 더 내리려면 0.50 까지가 한계로 보인다 — 문장 중간 0.20 과의 비가
# 3:1 아래로 내려가면 문단 구분이 안 들린다.
#
# min_saving 0.15 는 그대로 둔다. 0.05 로 낮추면 문장 중간 0.25~0.40초짜리
# 33곳이 정리되지만 벌이는 3초뿐이고 컷 지점만 33개 늘어난다.
#
# 쉼이 길게 느껴진다는 말이 또 나오면, 파라미터를 손대기 전에 위처럼
# '편집본에서 실제로 들리는 쉼'을 먼저 재라. 상한값과 체감은 다르다.


def load_deletions(retakes_paths, words):
    """재발화 삭제 지시 -> 시간 범위 목록

    두 가지 형식을 모두 받는다:
      - 단어 인덱스 기반 {from_i, to_i}  (전사본을 LLM이 읽고 판단한 것)
      - 시간 기반      {from_t, to_t}    (전사본에 안 보이던 재발화.
        find_hidden_retakes 가 발화 덩어리를 따로 재전사해 찾아낸 것)
    """
    if isinstance(retakes_paths, (str, Path)):
        retakes_paths = [retakes_paths]
    by_i = {w["i"]: w for w in words}
    ranges, info = [], []
    for path in retakes_paths or []:
        if not path or not Path(path).exists():
            continue
        r = json.loads(Path(path).read_text(encoding="utf-8"))
        for d in r.get("deletions", []):
            if "from_t" in d:
                ranges.append([float(d["from_t"]), float(d["to_t"])])
                info.append(d)
                continue
            ws = [by_i[i] for i in range(d["from_i"], d["to_i"] + 1)
                  if i in by_i]
            if not ws:
                continue
            ranges.append([min(w["start"] for w in ws),
                           max(w["end"] for w in ws)])
            info.append(d)
    return ranges, info


def overlap(a, b):
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def plan(speech_path, words_path, out_path, *retakes_paths, params=None,
         scene_times=None):
    """scene_times: 장면이 바뀌는 원본 시각들. 그 자리 컷은 쉼을 더 준다."""
    p = dict(PARAMS)
    if params:
        p.update(params)
    scenes = sorted(scene_times or [])

    sp = json.loads(Path(speech_path).read_text(encoding="utf-8"))
    segments = [list(s) for s in sp["speech"]]
    # 길이가 0 에 가까운 VAD 구간은 발화일 수 없다. 게다가 아래 삭제 판정이
    # '구간 길이 대비 겹침 비율' 이라 길이 0 은 어떤 삭제 지시로도 지워지지
    # 않는다. 그대로 두면 재발화를 지운 자리에 1초짜리 빈 조각으로 남는다.
    # (3차시 281.2 초에서 실제로 발생)
    degenerate = [s for s in segments if s[1] - s[0] < MIN_SEGMENT]
    segments = [s for s in segments if s[1] - s[0] >= MIN_SEGMENT]
    if degenerate:
        print(f"    길이 0 구간 {len(degenerate)}개 제외 "
              f"({', '.join(f'{s[0]:.1f}초' for s in degenerate[:5])})")
    if not segments:
        raise SystemExit("VAD 가 발화를 찾지 못했습니다")

    words = [w for w in json.loads(
        Path(words_path).read_text(encoding="utf-8"))["words"]
        if w["type"] == "word"]

    del_ranges, del_info = load_deletions(list(retakes_paths), words)

    # 검출기끼리 반대로 판단해 한 말의 모든 테이크를 지워버리는 사고를 막는다.
    # 2026-08-14 에 3차시 55:24 "이렇게 창을 여러개 만들어두고" 가 이렇게
    # 통째로 사라졌다. 자세한 내용은 resolve_delete_conflicts.py 주석 참고.
    from resolve_delete_conflicts import resolve as resolve_conflicts
    del_ranges, del_info, reverted = resolve_conflicts(
        segments, del_ranges, del_info, words, p["delete_overlap"])

    kept, dropped = [], 0
    unapplied = 0
    hit = [False] * len(del_ranges)
    for seg in segments:
        span = seg[1] - seg[0]
        ov = 0.0
        for k, d in enumerate(del_ranges):
            o = overlap(seg, d)
            if o > 0:
                ov += o
                if o / max(span, 1e-6) >= p["delete_overlap"]:
                    hit[k] = True
        if span > 0 and ov / span >= p["delete_overlap"]:
            dropped += 1
        else:
            kept.append(seg)
    applied_info = [d for d, h in zip(del_info, hit) if h]
    unapplied_info = [d for d, h in zip(del_info, hit) if not h]
    unapplied = len(unapplied_info)

    if not kept:
        raise SystemExit("남는 발화가 없습니다")

    # 여유분이 이웃 발화(삭제한 재발화 포함)를 물지 않도록 경계를 잡아둔다.
    # 이걸 안 하면 지운 재발화의 꼬리가 파편으로 끼어든다.
    import bisect
    all_starts = sorted(s for s, _ in segments)
    all_ends = sorted(e for _, e in segments)
    EPS = 0.05

    def room_after(t):
        i = bisect.bisect_right(all_starts, t)
        return (all_starts[i] - EPS - t) if i < len(all_starts) else 1e9

    def room_before(t):
        i = bisect.bisect_left(all_ends, t) - 1
        return (t - (all_ends[i] + EPS)) if i >= 0 else 1e9

    # 컷 지점이 문장 끝인지 판정한다 (전사본에 문장부호가 있을 때만)
    w_ends = sorted(w["end"] for w in words)
    by_end = {w["end"]: w for w in words}
    punct_ratio = (sum(1 for w in words if w["text"].rstrip()[-1:] in ".?!")
                   / max(len(words), 1))
    has_punct = punct_ratio > 0.03

    def is_sentence_end(t):
        """t 직전 단어가 문장을 끝맺었나"""
        if not has_punct:
            return True          # 부호가 없는 전사본이면 넉넉한 쪽으로
        i = bisect.bisect_right(w_ends, t + 0.05) - 1
        if i < 0:
            return True
        return by_end[w_ends[i]]["text"].rstrip()[-1:] in ".?!"

    # 무음을 상한까지만 깎는다. 상한 이하의 쉼은 통째로 보존.
    total_dur = sp["duration"]
    blocks = []
    cur = [max(0.0, kept[0][0] - p["start_lead"]), kept[0][1]]
    n_cuts = 0
    n_mid = n_end = 0
    def near_scene(t, tol=1.5):
        i = bisect.bisect_left(scenes, t - tol)
        return i < len(scenes) and scenes[i] <= t + tol

    n_scene = 0
    for seg in kept[1:]:
        gap = seg[0] - cur[1]
        ends = is_sentence_end(cur[1])
        cap = p["max_silence_end"] if ends else p["max_silence_mid"]
        if scenes and near_scene(cur[1]):
            cap = max(cap, p["max_silence_scene"])
            n_scene += 1
        if gap - min(gap, cap) < p["min_saving"]:
            cur[1] = max(cur[1], seg[1])       # 자를 만큼 아끼지 못함 → 유지
            continue
        n_end, n_mid = (n_end + 1, n_mid) if ends else (n_end, n_mid + 1)
        avail_t = max(0.0, room_after(cur[1]))
        avail_l = max(0.0, room_before(seg[0]))
        # 뒷말 앞을 먼저 확보한다 (첫소리가 잘리지 않게)
        want_lead = max(cap * (1.0 - p["tail_ratio"]), p["min_lead"])
        want_lead = min(want_lead, max(0.0, cap - p["min_tail"]))
        lead = min(want_lead, avail_l)
        tail = min(cap - lead, avail_t)
        if tail + lead < cap:                  # 한쪽이 막히면 반대쪽에서 보충
            lead = min(avail_l, lead + (cap - tail - lead))
            tail = min(avail_t, tail + (cap - tail - lead))
        blocks.append([cur[0], cur[1] + tail])
        cur = [seg[0] - lead, seg[1]]
        n_cuts += 1
    cur[1] = min(total_dur, cur[1] + min(p["end_tail"], room_after(cur[1])))
    blocks.append(cur)

    padded = [[round(max(0.0, s), 3), round(min(total_dur, e), 3)]
              for s, e in blocks]
    kept_dur = sum(e - s for s, e in padded)
    result = {
        "params": p,
        "source": sp.get("source"),
        "boundary_source": "vad",
        "n_blocks": len(padded),
        "n_silence_cuts": n_cuts,
        "n_segments_deleted": dropped,
        "n_deletions_unapplied": unapplied,
        "retakes_applied": applied_info,
        "retakes_unapplied": unapplied_info,
        "src_duration": round(total_dur, 2),
        "kept_duration": round(kept_dur, 2),
        "keep_ranges": [[round(s, 3), round(e, 3)] for s, e in padded],
    }
    Path(out_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"    쉼 배분: 문장 끝 {n_end}곳({p['max_silence_end']}초), "
          f"문장 중간 {n_mid}곳({p['max_silence_mid']}초)"
          + (f", 장면 전환 {n_scene}곳({p['max_silence_scene']}초)"
             if n_scene else ""))
    print(f"OK: {len(padded)} blocks, 무음 컷 {n_cuts}곳, "
          f"재발화 구간 {dropped}개 제거")
    if unapplied:
        print(f"    (삭제 지시 {unapplied}건은 발화가 끊기지 않아 미적용 "
              f"— 보고서에서 직접 확인)")
    print(f"    {total_dur/60:.1f}분 -> {kept_dur/60:.1f}분 "
          f"({100*kept_dur/total_dur:.0f}%)")
    return result


if __name__ == "__main__":
    plan(sys.argv[1], sys.argv[2], sys.argv[3], *sys.argv[4:])
