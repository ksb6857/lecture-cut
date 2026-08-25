# -*- coding: utf-8 -*-
"""명령줄 인자를 위치 인자와 옵션으로 가른다.

`[x for x in sys.argv[1:] if not x.startswith("--")]` 로 거르면 **옵션의
값**까지 위치 인자에 섞인다. `--json parts.json out.mp4` 를 주면 `parts.json`
이 위치 인자로 들어가 마지막 인자(출력 파일)를 밀어낸다. 실제로 그렇게 해서
merge_parts 가 parts.json 을 영상으로 쓰려다 죽었다.

값을 받는 옵션 이름을 미리 알려 주면 그 다음 토큰을 같이 걷어낸다.

    pos, opt = split_args(sys.argv[1:], {"--json", "--fps"})
    pos   -> ["원본폴더", "out.mp4"]
    opt   -> {"--json": "parts.json", "--fps": "30"}

값이 없는 스위치(`--no-captions`)는 `opt` 에 `True` 로 담긴다.
"""


def split_args(argv, value_flags=()):
    value_flags = set(value_flags)
    pos, opt = [], {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            if a in value_flags:
                if i + 1 >= len(argv):
                    raise SystemExit(f"{a} 뒤에 값이 없습니다.")
                opt[a] = argv[i + 1]
                i += 2
                continue
            opt[a] = True
        else:
            pos.append(a)
        i += 1
    return pos, opt
