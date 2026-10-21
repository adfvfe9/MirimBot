"""선착순 퀴즈 자동 출제: 사실 표 + 문제 틀로 매번 다른 문제를 만든다.

문제를 통째로 적어 두면(quiz_bank.py) 금방 같은 문제가 반복된다.
여기서는 "사실"만 표로 적어 두고, 묻는 방향 / 오답 보기 / 숫자를 매번 바꿔서 낸다.
  예) 사건-연도 표 한 줄 → "몇 년?" / "가장 먼저 일어난 사건은?" / "1894년에 일어난 일은?"
표에 줄을 더 넣으면 문제가 그만큼 늘어난다. (사실이 맞는지만 꼭 확인!)

GENERATORS[과목][난이도] = [함수, ...], 함수는 quiz_bank.BANK 와 같은 모양의 dict 를 돌려준다.
    q, choices(객관식일 때), answer(객관식: 번호 / 주관식: 정답 목록), explain, unit(단원, 없어도 됨)
"""
import random
import re

# ───────────── 공통 도우미 ─────────────

def mc(question, correct, wrongs, explain=None, unit=None, k=4):
    """객관식: correct 하나 + wrongs 에서 k-1 개를 섞어서 보기로"""
    wrongs = [w for w in dict.fromkeys(wrongs) if w != correct]
    choices = random.sample(wrongs, k - 1) + [correct]
    random.shuffle(choices)
    return {"q": question, "choices": choices, "answer": choices.index(correct) + 1,
            "explain": explain, "unit": unit}


def short(question, answers, explain=None, unit=None):
    """주관식"""
    if not isinstance(answers, (list, tuple)):
        answers = [answers]
    return {"q": question, "answer": [str(a) for a in answers], "explain": explain, "unit": unit}


# ───────────── 한국사 ─────────────
# (사건, 연도, 유명함) 유명함 True 인 것만 '하' 난이도에 나온다.
EVENTS = [
    ("광개토 대왕 즉위", 391, False), ("장수왕의 평양 천도", 427, False), ("신라의 불교 공인(이차돈의 순교)", 527, False),
    ("살수 대첩", 612, True), ("안시성 싸움", 645, False), ("백제 멸망", 660, False), ("고구려 멸망", 668, False),
    ("신라의 삼국 통일 완성(나당 전쟁 승리)", 676, True), ("발해 건국", 698, True), ("고려 건국", 918, True),
    ("발해 멸망", 926, False), ("고려의 후삼국 통일", 936, True), ("광종의 과거제 실시", 958, False),
    ("서희의 외교 담판", 993, False), ("귀주 대첩", 1019, False), ("무신 정변", 1170, False),
    ("몽골의 고려 침입 시작", 1231, False), ("고려의 강화도 천도", 1232, False), ("삼별초의 항쟁 시작", 1270, False),
    ("위화도 회군", 1388, True), ("조선 건국", 1392, True), ("한양 천도", 1394, False),
    ("훈민정음 창제", 1443, True), ("훈민정음 반포", 1446, True), ("임진왜란 발발", 1592, True),
    ("명량 해전", 1597, False), ("경기도에 대동법 실시", 1608, False), ("정묘호란", 1627, False),
    ("병자호란", 1636, True), ("균역법 실시", 1750, False), ("수원 화성 완공", 1796, False),
    ("홍경래의 난", 1811, False), ("병인양요", 1866, False), ("신미양요", 1871, False),
    ("강화도 조약 체결", 1876, True), ("임오군란", 1882, False), ("갑신정변", 1884, True),
    ("동학 농민 운동", 1894, True), ("을미사변", 1895, False), ("아관 파천", 1896, False),
    ("대한 제국 수립", 1897, True), ("을사늑약 체결", 1905, True), ("국채 보상 운동", 1907, False),
    ("헤이그 특사 파견", 1907, False), ("안중근의 하얼빈 의거", 1909, True), ("국권 피탈(한일 병합)", 1910, True),
    ("3·1 운동", 1919, True), ("대한민국 임시 정부 수립", 1919, True), ("봉오동 전투", 1920, False),
    ("청산리 대첩", 1920, False), ("6·10 만세 운동", 1926, False), ("광주 학생 항일 운동", 1929, False),
    ("윤봉길의 훙커우 공원 의거", 1932, False), ("8·15 광복", 1945, True), ("대한민국 정부 수립", 1948, True),
    ("6·25 전쟁 발발", 1950, True), ("6·25 전쟁 정전 협정", 1953, True), ("4·19 혁명", 1960, True),
    ("5·16 군사 정변", 1961, False), ("5·18 민주화 운동", 1980, True), ("6월 민주 항쟁", 1987, True),
    ("서울 올림픽 개최", 1988, True), ("첫 남북 정상 회담", 2000, False), ("한일 월드컵 개최", 2002, True),
]

# (인물, 업적)
PEOPLE = [
    ("세종", "훈민정음 창제"), ("이순신", "한산도 대첩, 명량 해전"), ("을지문덕", "살수 대첩"),
    ("강감찬", "귀주 대첩"), ("서희", "거란과 외교 담판으로 강동 6주 획득"), ("장보고", "청해진 설치, 해상 무역"),
    ("대조영", "발해 건국"), ("왕건", "고려 건국, 후삼국 통일"), ("이성계", "위화도 회군, 조선 건국"),
    ("정도전", "조선 건국 설계, 『조선경국전』"), ("정조", "수원 화성 건설, 규장각 설치"),
    ("흥선 대원군", "경복궁 중건, 서원 철폐"), ("홍범도", "봉오동 전투"), ("김좌진", "청산리 대첩"),
    ("유관순", "아우내 장터 3·1 운동"), ("안중근", "하얼빈에서 이토 히로부미 저격"),
    ("윤봉길", "훙커우 공원 의거"), ("김구", "한인 애국단 조직, 임시 정부 주석"),
    ("장영실", "측우기·자격루 제작"), ("김정호", "「대동여지도」 제작"), ("허준", "『동의보감』 편찬"),
    ("정약용", "『목민심서』 저술, 거중기 설계"), ("박지원", "『열하일기』 저술"), ("최무선", "화약·화포 제작"),
    ("광종", "노비안검법, 과거제 실시"), ("공민왕", "반원 자주 정책, 쌍성총관부 수복"),
    ("원효", "불교 대중화, 아미타 신앙 보급"), ("의상", "화엄 사상, 부석사 창건"),
    ("주시경", "국어 문법 연구, '한글' 이름 보급"), ("신채호", "『조선상고사』, 민족주의 역사학"),
]


def history_year_mc():
    event, year, _ = random.choice([e for e in EVENTS if e[2]])
    wrongs = [y for _, y, _ in EVENTS if abs(y - year) >= 5]
    return mc(f"'{event}'이(가) 일어난 해는?", year, wrongs, unit="연도")


def history_year_short():
    event, year, _ = random.choice(EVENTS)
    return short(f"'{event}'은(는) 몇 년도에 일어났을까요? (숫자)", year, unit="연도")


def history_order(level):
    gap = 30 if level == "중" else 8
    for _ in range(100):
        picked = random.sample(EVENTS, 4)
        years = sorted(y for _, y, _ in picked)
        if all(b - a >= gap for a, b in zip(years, years[1:])) and (level == "중" or years[-1] - years[0] <= 150):
            break
    first = random.random() < 0.5
    target = min(picked, key=lambda e: e[1]) if first else max(picked, key=lambda e: e[1])
    explain = ", ".join(f"{e} {y}" for e, y, _ in sorted(picked, key=lambda e: e[1]))
    return mc(f"다음 중 가장 {'먼저' if first else '늦게'} 일어난 사건은?", target[0],
              [e for e, _, _ in picked], explain, unit="사건 순서")


def history_which_year():
    event, year, _ = random.choice(EVENTS)
    wrongs = [e for e, y, _ in EVENTS if abs(y - year) >= 10]
    return mc(f"{year}년에 일어난 일은?", event, wrongs, unit="연도")


def history_person():
    person, deed = random.choice(PEOPLE)
    return mc(f"다음 업적과 관련된 인물은?\n\"{deed}\"", person, [p for p, _ in PEOPLE], unit="인물")


def history_person_short():
    person, deed = random.choice(PEOPLE)
    return short(f"다음 업적과 관련된 인물은?\n\"{deed}\"", [person, person.replace(" ", "")], unit="인물")


# ───────────── 영어 (고등 필수 어휘) ─────────────
WORDS = [
    ("abandon", "버리다, 포기하다"), ("absorb", "흡수하다"), ("abundant", "풍부한"), ("accurate", "정확한"),
    ("achieve", "성취하다"), ("acquire", "얻다, 습득하다"), ("adapt", "적응하다"), ("adequate", "충분한, 적절한"),
    ("admire", "존경하다, 감탄하다"), ("advocate", "옹호하다"), ("affect", "영향을 미치다"), ("ancestor", "조상"),
    ("anxious", "불안해하는"), ("apparent", "명백한"), ("appreciate", "감사하다, 진가를 알다"), ("approve", "승인하다"),
    ("arrange", "정리하다, 준비하다"), ("assume", "가정하다, 추정하다"), ("attach", "붙이다"), ("attempt", "시도하다"),
    ("attitude", "태도"), ("attract", "끌어당기다"), ("available", "이용할 수 있는"), ("avoid", "피하다"),
    ("aware", "알고 있는"), ("behavior", "행동"), ("benefit", "이익, 혜택"), ("bias", "편견"),
    ("boundary", "경계"), ("brief", "짧은, 간단한"), ("capable", "할 수 있는, 유능한"), ("capture", "붙잡다, 포착하다"),
    ("cease", "그만두다, 멈추다"), ("chaos", "혼돈"), ("circumstance", "상황, 환경"), ("cite", "인용하다"),
    ("collapse", "붕괴하다"), ("combine", "결합하다"), ("commit", "저지르다, 전념하다"), ("compete", "경쟁하다"),
    ("complex", "복잡한"), ("conceal", "숨기다"), ("concentrate", "집중하다"), ("conclude", "결론을 내리다"),
    ("confirm", "확인하다"), ("conflict", "갈등"), ("consequence", "결과"), ("conserve", "보존하다"),
    ("consist", "구성되다"), ("constant", "끊임없는, 일정한"), ("consume", "소비하다"), ("contemporary", "동시대의, 현대의"),
    ("contradict", "모순되다, 반박하다"), ("contribute", "기여하다"), ("convert", "전환하다"), ("convince", "확신시키다"),
    ("cooperate", "협력하다"), ("crucial", "결정적인, 중대한"), ("curious", "호기심이 많은"), ("decline", "감소하다, 거절하다"),
    ("dedicate", "바치다, 헌신하다"), ("define", "정의하다"), ("delay", "지연시키다"), ("deliberate", "의도적인, 신중한"),
    ("demand", "요구하다"), ("deny", "부인하다"), ("depend", "의존하다"), ("deprive", "빼앗다"),
    ("derive", "유래하다, 끌어내다"), ("deserve", "~을 받을 만하다"), ("detect", "발견하다, 감지하다"), ("devote", "바치다, 쏟다"),
    ("diminish", "줄어들다"), ("disguise", "변장하다, 위장하다"), ("distinguish", "구별하다"), ("distract", "주의를 흐트러뜨리다"),
    ("diverse", "다양한"), ("dominant", "지배적인"), ("efficient", "효율적인"), ("eliminate", "제거하다"),
    ("emerge", "나타나다"), ("emphasize", "강조하다"), ("encounter", "마주치다"), ("endure", "견디다"),
    ("enhance", "향상시키다"), ("enormous", "거대한"), ("essential", "필수적인"), ("evaluate", "평가하다"),
    ("evident", "분명한"), ("evolve", "진화하다"), ("exaggerate", "과장하다"), ("exclude", "제외하다"),
    ("expand", "확장하다"), ("expose", "노출시키다"), ("extinct", "멸종된"), ("fragile", "깨지기 쉬운"),
    ("frequent", "빈번한"), ("fundamental", "근본적인"), ("generate", "생성하다"), ("genuine", "진짜의"),
    ("grateful", "감사하는"), ("guarantee", "보장하다"), ("hesitate", "망설이다"), ("hostile", "적대적인"),
    ("identical", "동일한"), ("ignore", "무시하다"), ("illustrate", "설명하다, 삽화를 넣다"), ("imitate", "모방하다"),
    ("immediate", "즉각적인"), ("impose", "부과하다, 강요하다"), ("indicate", "나타내다, 가리키다"), ("inevitable", "피할 수 없는"),
    ("inherit", "물려받다, 상속하다"), ("inspire", "영감을 주다"), ("intend", "의도하다"), ("interpret", "해석하다"),
    ("investigate", "조사하다"), ("isolate", "고립시키다"), ("maintain", "유지하다"), ("modest", "겸손한, 적당한"),
    ("motivate", "동기를 부여하다"), ("neglect", "방치하다, 소홀히 하다"), ("obey", "복종하다"), ("obscure", "모호한"),
    ("obstacle", "장애물"), ("obtain", "얻다"), ("occupy", "차지하다"), ("opponent", "상대, 반대자"),
    ("ordinary", "평범한"), ("overcome", "극복하다"), ("participate", "참여하다"), ("perceive", "인지하다"),
    ("permanent", "영구적인"), ("persuade", "설득하다"), ("precise", "정밀한"), ("predict", "예측하다"),
    ("prefer", "선호하다"), ("preserve", "보존하다, 지키다"), ("prevent", "막다, 예방하다"), ("previous", "이전의"),
    ("prohibit", "금지하다"), ("prominent", "두드러진, 저명한"), ("promote", "촉진하다, 승진시키다"), ("proper", "적절한"),
    ("pursue", "추구하다"), ("reluctant", "꺼리는"), ("remarkable", "주목할 만한"), ("remote", "먼, 외딴"),
    ("replace", "대체하다"), ("resemble", "닮다"), ("resist", "저항하다"), ("restore", "복원하다"),
    ("retire", "은퇴하다"), ("reveal", "드러내다"), ("rural", "시골의"), ("scarce", "부족한, 드문"),
    ("severe", "심각한, 가혹한"), ("sincere", "진실한"), ("solitary", "혼자의, 고독한"), ("sufficient", "충분한"),
    ("superior", "우수한, 상급의"), ("suppress", "억압하다"), ("sustain", "지속시키다"), ("temporary", "일시적인"),
    ("tolerate", "참다, 용인하다"), ("transform", "변형시키다"), ("ubiquitous", "어디에나 있는"), ("urban", "도시의"),
    ("vague", "막연한, 모호한"), ("vast", "광대한"), ("vulnerable", "취약한"), ("withdraw", "철회하다, 인출하다"),
]
# 반의어 (단어, 반의어)
ANTONYMS = [
    ("increase", "decrease"), ("include", "exclude"), ("accept", "reject"), ("ancient", "modern"),
    ("permanent", "temporary"), ("urban", "rural"), ("import", "export"), ("maximum", "minimum"),
    ("superior", "inferior"), ("visible", "invisible"), ("expand", "shrink"), ("rough", "smooth"),
    ("generous", "stingy"), ("victory", "defeat"), ("abundant", "scarce"), ("artificial", "natural"),
    ("praise", "criticize"), ("guilty", "innocent"), ("majority", "minority"), ("optimistic", "pessimistic"),
]


def english_meaning():
    word, meaning = random.choice(WORDS)
    return mc(f"'{word}'의 뜻은?", meaning, [m for _, m in WORDS], unit="어휘")


def english_word():
    word, meaning = random.choice(WORDS)
    return mc(f"'{meaning}'이라는 뜻의 영어 단어는?", word, [w for w, _ in WORDS], unit="어휘")


def english_spell():
    word, meaning = random.choice(WORDS)
    return short(f"'{meaning}'이라는 뜻의 영어 단어를 쓰세요. (첫 글자: {word[0]}, {len(word)}글자)", word,
                 unit="어휘")


def english_antonym():
    a, b = random.choice(ANTONYMS)
    if random.random() < 0.5:
        a, b = b, a
    pool = [x for pair in ANTONYMS for x in pair if x not in (a, b)]
    return mc(f"'{a}'의 반의어는?", b, pool, unit="반의어")


# ───────────── 과학 ─────────────
# (이름, 기호, 원자 번호)
ELEMENTS = [
    ("수소", "H", 1), ("헬륨", "He", 2), ("리튬", "Li", 3), ("베릴륨", "Be", 4), ("붕소", "B", 5),
    ("탄소", "C", 6), ("질소", "N", 7), ("산소", "O", 8), ("플루오린", "F", 9), ("네온", "Ne", 10),
    ("나트륨", "Na", 11), ("마그네슘", "Mg", 12), ("알루미늄", "Al", 13), ("규소", "Si", 14), ("인", "P", 15),
    ("황", "S", 16), ("염소", "Cl", 17), ("아르곤", "Ar", 18), ("칼륨", "K", 19), ("칼슘", "Ca", 20),
    ("철", "Fe", 26), ("구리", "Cu", 29), ("아연", "Zn", 30), ("은", "Ag", 47), ("금", "Au", 79),
    ("수은", "Hg", 80), ("납", "Pb", 82),
]
# (물질, 화학식, 분자량)
MOLECULES = [("물", "H₂O", 18), ("이산화 탄소", "CO₂", 44), ("산소 기체", "O₂", 32), ("암모니아", "NH₃", 17),
             ("메테인", "CH₄", 16), ("질소 기체", "N₂", 28), ("수소 기체", "H₂", 2)]


def element_symbol():
    name, symbol, _ = random.choice(ELEMENTS)
    if random.random() < 0.5:
        return mc(f"원소 '{name}'의 원소 기호는?", symbol, [s for _, s, _ in ELEMENTS], unit="원소")
    return mc(f"원소 기호 '{symbol}'인 원소는?", name, [n for n, _, _ in ELEMENTS], unit="원소")


def element_symbol_short():
    name, symbol, _ = random.choice(ELEMENTS)
    return short(f"원소 '{name}'의 원소 기호를 쓰세요.", symbol, unit="원소")


def element_number():
    name, symbol, number = random.choice(ELEMENTS[:20])
    return short(f"원소 '{name}'({symbol})의 원자 번호는? (숫자)", number, unit="원소")


def physics_easy():
    kind = random.randint(1, 4)
    if kind == 1:
        m, a = random.randint(1, 10), random.randint(1, 10)
        return short(f"질량 {m} kg인 물체가 {a} m/s²로 가속될 때 작용한 알짜힘은 몇 N? (숫자)", m * a, "F = ma", "힘")
    if kind == 2:
        v, t = random.randint(2, 30), random.randint(2, 12)
        return short(f"{v} m/s로 {t}초 동안 일정하게 움직인 물체의 이동 거리는 몇 m? (숫자)", v * t, "거리 = 속력 × 시간", "운동")
    if kind == 3:
        i, r = random.randint(1, 6), random.randint(2, 20)
        return short(f"저항이 {r} Ω인 전구에 {i} A의 전류가 흐를 때 걸린 전압은 몇 V? (숫자)", i * r, "V = IR", "전기")
    f, s = random.randint(2, 20), random.randint(2, 10)
    return short(f"{f} N의 힘으로 물체를 힘의 방향으로 {s} m 밀었을 때 한 일은 몇 J? (숫자)", f * s, "W = Fs", "일")


def physics_mid():
    kind = random.randint(1, 4)
    if kind == 1:
        m, v = random.choice([2, 4, 6, 8, 10]), random.randint(1, 10)
        return short(f"질량 {m} kg인 물체가 {v} m/s로 움직일 때 운동 에너지는 몇 J? (숫자)", m * v * v // 2,
                     "Eₖ = ½mv²", "에너지")
    if kind == 2:
        m, h = random.randint(1, 10), random.randint(1, 20)
        return short(f"질량 {m} kg인 물체를 {h} m 들어 올렸을 때 증가한 중력 퍼텐셜 에너지는 몇 J? (g = 10 m/s², 숫자)",
                     m * 10 * h, "Eₚ = mgh", "에너지")
    if kind == 3:
        v, i = random.randint(2, 20) * 5, random.randint(1, 5)
        return short(f"{v} V의 전압에서 {i} A의 전류가 흐르는 전기 기구의 소비 전력은 몇 W? (숫자)", v * i, "P = VI", "전기")
    m, v = random.randint(1, 10), random.randint(1, 10)
    return short(f"질량 {m} kg인 물체가 {v} m/s로 움직일 때 운동량의 크기는 몇 kg·m/s? (숫자)", m * v, "p = mv", "운동량")


def physics_hard():
    kind = random.randint(1, 5)
    if kind == 4:
        c, m, dt = random.choice([1, 2, 4]), random.randint(2, 20) * 5, random.randint(2, 20)
        return short(f"비열이 {c} J/(g·℃)인 물질 {m} g의 온도를 {dt} ℃ 높이는 데 필요한 열량은 몇 J? (숫자)", c * m * dt,
                     "Q = cmΔt", "열")
    if kind == 5:
        t = random.randint(2, 9)
        return short(f"정지 상태에서 자유 낙하한 물체의 {t}초 후 속력은 몇 m/s? (g = 10 m/s², 공기 저항 무시, 숫자)",
                     10 * t, "v = gt", "운동")
    if kind == 1:
        r1, r2, r = random.choice([(3, 6, 2), (4, 12, 3), (6, 12, 4), (10, 15, 6), (12, 24, 8), (6, 3, 2), (20, 30, 12)])
        return short(f"{r1} Ω과 {r2} Ω의 저항을 병렬로 연결했을 때 합성 저항은 몇 Ω? (숫자)", r,
                     "1/R = 1/R₁ + 1/R₂", "전기")
    if kind == 2:
        t = random.randint(1, 6)
        return short(f"정지 상태에서 자유 낙하한 물체가 {t}초 동안 떨어진 거리는 몇 m? (g = 10 m/s², 공기 저항 무시, 숫자)",
                     5 * t * t, "s = ½gt²", "운동")
    v = random.choice([10, 20, 30, 40])
    return short(f"물체를 {v} m/s로 연직 위로 던졌을 때 올라가는 최고 높이는 몇 m? (g = 10 m/s², 공기 저항 무시, 숫자)",
                 v * v // 20, "h = v₀² / 2g", "운동")


def chemistry_mol():
    name, formula, mass = random.choice(MOLECULES)
    n = random.randint(2, 6)
    if random.random() < 0.5:
        return short(f"{name}({formula}) {mass * n} g은 몇 몰(mol)? (분자량 {mass}, 숫자)", n, "몰 수 = 질량 ÷ 분자량", "몰")
    return short(f"{name}({formula}) {n}몰의 질량은 몇 g? (분자량 {mass}, 숫자)", mass * n, "질량 = 몰 수 × 분자량", "몰")


# ───────────── 상식 (정보 / 세계) ─────────────
# (나라, 수도, 어려움)
CAPITALS = [
    ("일본", "도쿄", False), ("중국", "베이징", False), ("미국", "워싱턴 D.C.", False), ("영국", "런던", False),
    ("프랑스", "파리", False), ("독일", "베를린", False), ("이탈리아", "로마", False), ("스페인", "마드리드", False),
    ("러시아", "모스크바", False), ("이집트", "카이로", False), ("태국", "방콕", False), ("베트남", "하노이", False),
    ("인도", "뉴델리", False), ("그리스", "아테네", False), ("캐나다", "오타와", True), ("호주", "캔버라", True),
    ("브라질", "브라질리아", True), ("튀르키예", "앙카라", True), ("스위스", "베른", True), ("뉴질랜드", "웰링턴", True),
    ("인도네시아", "자카르타", False), ("필리핀", "마닐라", False), ("아르헨티나", "부에노스아이레스", True),
    ("멕시코", "멕시코시티", False), ("포르투갈", "리스본", True), ("네덜란드", "암스테르담", True),
    ("오스트리아", "빈", True), ("스웨덴", "스톡홀름", True), ("노르웨이", "오슬로", True), ("핀란드", "헬싱키", True),
    ("덴마크", "코펜하겐", True), ("폴란드", "바르샤바", True), ("몽골", "울란바토르", True), ("케냐", "나이로비", True),
    ("페루", "리마", True), ("칠레", "산티아고", True), ("사우디아라비아", "리야드", True), ("이란", "테헤란", True),
    ("말레이시아", "쿠알라룸푸르", True), ("우크라이나", "키이우", True),
]


def capital(level):
    pool = [c for c in CAPITALS if c[2] == (level != "하")]
    country, city, _ = random.choice(pool)
    if level == "상":
        return short(f"{country}의 수도는?", [city, city.replace(" ", "")], unit="세계 수도")
    return mc(f"{country}의 수도는?", city, [c for _, c, _ in CAPITALS], unit="세계 수도")


def binary_to_decimal(bits):
    n = random.randint(2 ** (bits - 1), 2 ** bits - 1)
    return short(f"2진수 {n:b}을(를) 10진수로 바꾸면? (숫자)", n, unit="진법")


def decimal_to_binary():
    n = random.randint(5, 63)
    return short(f"10진수 {n}을(를) 2진수로 바꾸면?", f"{n:b}", unit="진법")


def hex_convert():
    n = random.randint(17, 255)
    if random.random() < 0.5:
        return short(f"16진수 {n:X}을(를) 10진수로 바꾸면? (숫자)", n, unit="진법")
    return short(f"10진수 {n}을(를) 16진수로 바꾸면?", [f"{n:X}", f"0x{n:X}"], unit="진법")


def bitwise():
    a, b = random.randint(5, 31), random.randint(5, 31)
    op, sym = random.choice([("AND", "&"), ("OR", "|"), ("XOR", "^")])
    ans = {"&": a & b, "|": a | b, "^": a ^ b}[sym]
    return short(f"파이썬에서 print({a} {sym} {b}) 의 출력은? (비트 {op}, 숫자)", ans,
                 f"{a} = {a:05b}, {b} = {b:05b} → {ans:05b}", "비트 연산")


def python_output(level):
    """파이썬 코드 실행 결과. 코드와 답은 여기서 직접 계산한다."""
    if level == "중":
        kind = random.randint(1, 4)
        if kind == 1:
            a, b = random.randint(10, 50), random.randint(2, 9)
            code, ans = f"print({a} // {b} + {a} % {b})", a // b + a % b
        elif kind == 2:
            s, n = random.choice(["ab", "abc", "미림", "코딩"]), random.randint(2, 5)
            code, ans = f"print(len(\"{s}\" * {n}))", len(s) * n
        elif kind == 3:
            a, b = random.randint(1, 5), random.randint(6, 12)
            code, ans = f"print(sum(range({a}, {b})))", sum(range(a, b))
        else:
            lst = random.sample(range(1, 30), 5)
            code, ans = f"print(max({lst}) - min({lst}))", max(lst) - min(lst)
    else:
        kind = random.randint(1, 3)
        if kind == 1:
            x, n, m = random.randint(1, 4), random.randint(3, 5), random.randint(2, 3)
            code = f"x = {x}\nfor i in range({n}):\n    x = x * {m} - 1\nprint(x)"
            ans = x
            for _ in range(n):
                ans = ans * m - 1
        elif kind == 2:
            n = random.randint(4, 8)
            code, ans = f"print([i * i for i in range({n})][-1] + len(range({n})))", (n - 1) ** 2 + n
        else:
            word = random.choice(["programming", "discord", "mirimbot", "python", "computer"])
            i, j = sorted(random.sample(range(len(word) + 1), 2))
            code, ans = f"print(\"{word}\"[{i}:{j}])", word[i:j]
    return short(f"다음 파이썬 코드의 출력은?\n```python\n{code}\n```", ans, unit="파이썬")


# ───────────── 상식: 분야별 사실 표 ─────────────
# (질문, 정답, 난이도, 오답 목록)
#   정답이 숫자면 숫자 주관식, 아니면 객관식 (상 난이도는 절반은 직접 쓰는 주관식)
#   정답을 여러 표기로 인정하려면 ("대표 표기", "다른 표기", ...) 처럼 묶는다.
#   오답 목록이 None 이면 같은 분야의 다른 정답들 중에서 오답 보기를 뽑는다. (정답들이 모두 같은 종류일 때만!)
TRIVIA = {
    "스포츠": [
        ("축구 경기에서 한 팀이 경기장에 내보내는 선수는 몇 명?", 11, "하", None),
        ("농구 경기에서 한 팀이 코트에 내보내는 선수는 몇 명?", 5, "하", None),
        ("배구(6인제) 경기에서 한 팀이 코트에 내보내는 선수는 몇 명?", 6, "하", None),
        ("야구에서 수비하는 팀의 선수는 몇 명?", 9, "하", None),
        ("하계 올림픽은 몇 년마다 열릴까?", 4, "하", None),
        ("골프 정규 한 라운드는 몇 홀?", 18, "중", None),
        ("볼링에서 퍼펙트 게임의 점수는?", 300, "중", None),
        ("바둑판의 가로줄은 몇 줄?", 19, "중", None),
        ("체스에서 한 사람이 처음에 가지고 시작하는 말은 몇 개?", 16, "중", None),
        ("마라톤 풀코스 거리는 약 몇 km? (소수점 아래 버림)", 42, "중", None),
        ("2002년 한일 월드컵에서 대한민국의 최종 순위는? (숫자)", 4, "중", None),
        ("FIFA 월드컵에서 가장 많이 우승한 나라는?", "브라질", "중", ["독일", "이탈리아", "아르헨티나", "프랑스", "잉글랜드"]),
        ("2024년 하계 올림픽이 열린 도시는?", "파리", "하", ["런던", "도쿄", "로스앤젤레스", "베이징", "리우데자네이루"]),
        ("2018년 동계 올림픽이 열린 대한민국의 도시는?", "평창", "하", ["강릉", "서울", "부산", "춘천", "인천"]),
        ("2028년 하계 올림픽이 열릴 도시는?", "로스앤젤레스", "상", ["브리즈번", "파리", "도쿄", "런던", "뉴욕"]),
        ("테니스 4대 메이저 대회 중 잔디 코트에서 열리는 대회는?", "윔블던", "상",
         ["US 오픈", "프랑스 오픈", "호주 오픈"]),
        ("대한민국이 종주국인 올림픽 정식 종목은?", "태권도", "하", ["유도", "가라테", "레슬링", "펜싱", "복싱"]),
    ],
    "음악": [  # 정답이 모두 작곡가
        ("교향곡 「운명」(제5번)을 작곡한 사람은?", "베토벤", "하", None),
        ("협주곡 「사계」를 작곡한 사람은?", "비발디", "중", None),
        ("오페라 「마술피리」를 작곡한 사람은?", "모차르트", "중", None),
        ("발레 음악 「호두까기 인형」을 작곡한 사람은?", "차이콥스키", "중", None),
        ("가곡 「마왕」을 작곡한 사람은?", "슈베르트", "상", None),
        ("오페라 「카르멘」을 작곡한 사람은?", "비제", "상", None),
        ("오라토리오 「메시아」를 작곡한 사람은?", "헨델", "상", None),
        ("'피아노의 시인'이라 불리며 「강아지 왈츠」를 작곡한 사람은?", "쇼팽", "중", None),
        ("'음악의 아버지'라고 불리는 바로크 시대 작곡가는?", "바흐", "하", None),
    ],
    "서양 미술": [  # 정답이 모두 화가·조각가
        ("그림 「별이 빛나는 밤」을 그린 화가는?", ("고흐", "반고흐", "빈센트반고흐"), "하", None),
        ("그림 「게르니카」를 그린 화가는?", "피카소", "중", None),
        ("그림 「최후의 만찬」과 「모나리자」를 그린 화가는?", ("레오나르도 다빈치", "다빈치", "레오나르도"), "하", None),
        ("조각 「생각하는 사람」을 만든 사람은?", "로댕", "중", None),
        ("그림 「절규」를 그린 화가는?", "뭉크", "중", None),
        ("「수련」 연작과 「인상, 해돋이」를 그린 인상파 화가는?", "모네", "상", None),
        ("시스티나 성당 천장화 「천지창조」를 그린 사람은?", "미켈란젤로", "상", None),
        ("그림 「이삭 줍기」와 「만종」을 그린 화가는?", "밀레", "상", None),
    ],
    "한국 미술": [  # 정답이 모두 조선 화가
        ("풍속화 「씨름」, 「서당」을 그린 조선의 화가는?", ("김홍도", "단원"), "중", None),
        ("풍속화 「미인도」를 그린 조선의 화가는?", ("신윤복", "혜원"), "상", None),
        ("진경산수화 「인왕제색도」를 그린 조선의 화가는?", ("정선", "겸재"), "상", None),
        ("「세한도」를 그리고 추사체를 만든 조선의 학자는?", ("김정희", "추사"), "상", None),
    ],
    "문학": [  # 정답이 모두 작가
        ("희곡 「햄릿」을 쓴 작가는?", "셰익스피어", "하", None),
        ("소설 「돈키호테」를 쓴 작가는?", "세르반테스", "상", None),
        ("소설 「어린 왕자」를 쓴 작가는?", "생텍쥐페리", "중", None),
        ("소설 「노인과 바다」를 쓴 작가는?", "헤밍웨이", "중", None),
        ("소설 「죄와 벌」을 쓴 작가는?", ("도스토옙스키", "도스토예프스키"), "상", None),
        ("소설 「전쟁과 평화」를 쓴 작가는?", "톨스토이", "상", None),
        ("소설 「변신」(아침에 일어나니 벌레가 된 이야기)을 쓴 작가는?", "카프카", "상", None),
        ("소설 「레 미제라블」을 쓴 작가는?", ("빅토르 위고", "위고"), "중", None),
        ("2024년 노벨 문학상을 받은 한국 작가는?", "한강", "하", None),
    ],
    "세계 지리": [
        ("세계에서 가장 넓은 대양은?", "태평양", "하", ["대서양", "인도양", "북극해", "남극해"]),
        ("세계에서 가장 넓은 사막은? (극지방 제외)", ("사하라 사막", "사하라"), "중", ["고비 사막", "아라비아 사막", "칼라하리 사막", "아타카마 사막"]),
        ("세계에서 인구가 가장 많은 나라는? (2023년 이후)", "인도", "중", ["중국", "미국", "인도네시아", "파키스탄"]),
        ("세계에서 면적이 가장 작은 나라는?", ("바티칸 시국", "바티칸"), "중", ["모나코", "산마리노", "리히텐슈타인", "몰타"]),
        ("세계에서 가장 큰 섬은?", "그린란드", "상", ["보르네오섬", "마다가스카르", "뉴기니섬", "아이슬란드"]),
        ("남한에서 가장 높은 산은?", "한라산", "하", ["지리산", "설악산", "태백산", "북한산"]),
        ("남한에서 가장 긴 강은?", ("낙동강", "낙동"), "중", ["한강", "금강", "영산강", "섬진강"]),
        ("대한민국에서 가장 큰 섬은?", ("제주도", "제주"), "하", ["거제도", "진도", "강화도", "울릉도"]),
        ("대한민국의 가장 동쪽 끝에 있는 섬은?", "독도", "하", ["울릉도", "마라도", "백령도", "제주도"]),
        ("남아메리카 서쪽을 따라 길게 뻗은 산맥은?", ("안데스 산맥", "안데스"), "상", ["로키 산맥", "알프스 산맥", "히말라야 산맥", "우랄 산맥"]),
        ("유럽과 아시아를 나누는 경계로 꼽히는 산맥은?", ("우랄 산맥", "우랄"), "상", ["알프스 산맥", "피레네 산맥", "안데스 산맥", "애팔래치아 산맥"]),
    ],
    "랜드마크": [  # 정답이 모두 나라 이름
        ("자유의 여신상이 있는 나라는?", "미국", "하", None),
        ("에펠탑이 있는 나라는?", "프랑스", "하", None),
        ("콜로세움이 있는 나라는?", "이탈리아", "하", None),
        ("타지마할이 있는 나라는?", "인도", "중", None),
        ("마추픽추가 있는 나라는?", "페루", "상", None),
        ("앙코르 와트가 있는 나라는?", "캄보디아", "상", None),
        ("오페라 하우스로 유명한 시드니가 있는 나라는?", "호주", "하", None),
        ("기자의 피라미드가 있는 나라는?", "이집트", "하", None),
        ("만리장성이 있는 나라는?", "중국", "하", None),
        ("사그라다 파밀리아 성당이 있는 나라는?", "스페인", "중", None),
        ("빅벤이 있는 나라는?", "영국", "하", None),
        ("브란덴부르크 문이 있는 나라는?", "독일", "중", None),
        ("파르테논 신전이 있는 나라는?", "그리스", "중", None),
        ("페트라 유적이 있는 나라는?", "요르단", "상", None),
    ],
    "세계 음식": [  # 정답이 모두 나라 이름
        ("스시(초밥)가 유래한 나라는?", "일본", "하", None),
        ("파에야가 유래한 나라는?", "스페인", "중", None),
        ("쌀국수 '퍼(phở)'가 유래한 나라는?", "베트남", "하", None),
        ("타코가 유래한 나라는?", "멕시코", "하", None),
        ("마르게리타 피자가 유래한 나라는?", "이탈리아", "하", None),
        ("똠얌꿍이 유래한 나라는?", "태국", "중", None),
        ("케밥이 유래한 나라는?", "튀르키예", "중", None),
        ("크루아상이 대표 빵인 나라는?", "프랑스", "하", None),
        ("프레첼과 소시지, 맥주 축제 옥토버페스트로 유명한 나라는?", "독일", "중", None),
        ("탄두리 치킨이 유래한 나라는?", "인도", "중", None),
        ("슈하스코(꼬치 바비큐)로 유명한 나라는?", "브라질", "상", None),
        ("보르시(붉은 비트 수프)로 유명한 나라는?", "우크라이나", "상", None),
    ],
    "동물": [
        ("세상에서 가장 큰 동물은?", ("대왕고래", "흰긴수염고래"), "중", ["향유고래", "아프리카코끼리", "고래상어", "범고래"]),
        ("육지에서 가장 빠른 동물은?", "치타", "하", ["사자", "말", "가젤", "표범"]),
        ("포유류이면서 알을 낳는 동물은?", "오리너구리", "중", ["박쥐", "고래", "캥거루", "아르마딜로"]),
        ("하늘을 날 수 있는 포유류는?", "박쥐", "하", ["날다람쥐", "타조", "펭귄", "오리너구리"]),
        ("곤충의 다리는 몇 개?", 6, "하", None),
        ("거미의 다리는 몇 개?", 8, "하", None),
        ("판다가 주로 먹는 것은?", "대나무", "하", ["유칼립투스", "물고기", "꿀", "도토리"]),
        ("코알라가 주로 먹는 것은?", ("유칼립투스", "유칼립투스 잎"), "중", ["대나무", "바나나", "곤충", "도토리"]),
        ("새끼를 배에 있는 주머니에서 키우는 동물은?", "캥거루", "하", ["너구리", "수달", "비버", "판다"]),
        ("카멜레온이 몸 색깔을 바꾸는 주된 목적이 아닌 것은?", "광합성", "상", ["의사소통", "체온 조절", "위장"]),
    ],
    "발명·과학자": [  # 정답이 모두 사람 이름
        ("전화기를 발명한 것으로 알려진 사람은?", ("벨", "그레이엄벨", "알렉산더그레이엄벨"), "하", None),
        ("백열전구를 실용화한 사람은?", "에디슨", "하", None),
        ("동력 비행기로 처음 비행에 성공한 형제는?", ("라이트 형제", "라이트"), "하", None),
        ("다이너마이트를 발명하고 노벨상을 만든 사람은?", "노벨", "하", None),
        ("페니실린을 발견한 사람은?", "플레밍", "중", None),
        ("상대성 이론을 발표한 과학자는?", "아인슈타인", "하", None),
        ("만유인력의 법칙을 발견한 과학자는?", "뉴턴", "하", None),
        ("『종의 기원』을 써서 진화론을 주장한 사람은?", "다윈", "중", None),
        ("지동설을 주장한 사람은?", "코페르니쿠스", "중", None),
        ("월드 와이드 웹(WWW)을 만든 사람은?", ("팀 버너스리", "버너스리"), "상", None),
        ("금속 활자 인쇄기로 성경을 찍어 낸 독일 사람은?", "구텐베르크", "상", None),
        ("방사능을 연구해 노벨상을 두 번 받은 과학자는?", ("마리 퀴리", "퀴리", "퀴리부인"), "중", None),
        ("전자기 유도 현상을 발견한 과학자는?", "패러데이", "상", None),
        ("종두법(천연두 백신)을 개발한 사람은?", "제너", "상", None),
        ("프로그래밍 언어 파이썬을 만든 사람은?", ("귀도 반 로섬", "귀도"), "중", None),
        ("리눅스와 깃(Git)을 만든 사람은?", ("리누스 토르발스", "토르발스", "리누스"), "상", None),
        ("튜링 기계를 고안해 '컴퓨터 과학의 아버지'로 불리는 사람은?", ("앨런 튜링", "튜링"), "중", None),
    ],
    "IT 약어": [  # 정답이 모두 영어 풀네임
        ("CPU의 원래 말은?", "Central Processing Unit", "하", None),
        ("GPU의 원래 말은?", "Graphics Processing Unit", "중", None),
        ("RAM의 원래 말은?", "Random Access Memory", "중", None),
        ("URL의 원래 말은?", "Uniform Resource Locator", "상", None),
        ("AI의 원래 말은?", "Artificial Intelligence", "하", None),
        ("USB의 원래 말은?", "Universal Serial Bus", "중", None),
        ("OS의 원래 말은?", "Operating System", "하", None),
        ("SQL의 원래 말은?", "Structured Query Language", "상", None),
        ("API의 원래 말은?", "Application Programming Interface", "중", None),
        ("HTTP의 원래 말은?", "HyperText Transfer Protocol", "중", None),
        ("PDF의 원래 말은?", "Portable Document Format", "상", None),
        ("LAN의 원래 말은?", "Local Area Network", "중", None),
        ("IoT의 원래 말은?", "Internet of Things", "하", None),
        ("DNS의 원래 말은?", "Domain Name System", "상", None),
    ],
    "우주": [
        ("태양계에서 가장 큰 행성은?", "목성", "하", None),
        ("태양에서 가장 가까운 행성은?", "수성", "하", None),
        ("두꺼운 이산화 탄소 대기 때문에 태양계에서 가장 뜨거운 행성은?", "금성", "중", None),
        ("붉은 행성이라고 불리는 행성은?", "화성", "하", None),
        ("고리가 가장 뚜렷하게 보이는 행성은?", "토성", "하", None),
        ("자전축이 거의 누운 채로 도는 행성은?", "천왕성", "상", None),
        ("태양계에서 태양으로부터 가장 먼 행성은?", "해왕성", "중", None),
        ("태양에서 세 번째로 가까운 행성은?", "지구", "하", None),
        ("태양계의 행성은 모두 몇 개?", 8, "하", None),
    ],
    "인체": [
        ("어른의 몸에 있는 뼈는 약 몇 개?", 206, "중", None),
        ("사람의 심장은 몇 개의 방(심방·심실)으로 나뉠까?", 4, "하", None),
        ("사람 몸에서 가장 큰 기관은?", "피부", "중", ["간", "폐", "뇌", "소장"]),
        ("혈액에서 산소를 운반하는 것은?", "적혈구", "하", ["백혈구", "혈소판", "혈장"]),
        ("혈액에서 병균을 잡아먹어 몸을 지키는 것은?", "백혈구", "하", ["적혈구", "혈소판", "혈장"]),
        ("상처가 났을 때 피를 굳게 해 출혈을 멈추는 것은?", "혈소판", "중", ["적혈구", "백혈구", "혈장"]),
        ("혈당을 낮추는 호르몬 인슐린을 분비하는 기관은?", ("이자", "췌장"), "중", ["간", "쓸개", "콩팥", "갑상샘"]),
        ("쓸개즙을 만드는 기관은?", "간", "상", ["쓸개", "이자", "위", "소장"]),
        ("침 속에 있어 녹말을 분해하는 소화 효소는?", ("아밀레이스", "아밀라아제"), "상", ["펩신", "라이페이스", "트립신"]),
        ("위에서 단백질을 분해하는 소화 효소는?", "펩신", "상", ["아밀레이스", "라이페이스", "인슐린"]),
    ],
    "기념일": [  # 정답이 모두 날짜
        ("한글날은 몇 월 며칠?", "10월 9일", "하", None),
        ("광복절은 몇 월 며칠?", "8월 15일", "하", None),
        ("삼일절은 몇 월 며칠?", "3월 1일", "하", None),
        ("현충일은 몇 월 며칠?", "6월 6일", "중", None),
        ("개천절은 몇 월 며칠?", "10월 3일", "중", None),
        ("제헌절은 몇 월 며칠?", "7월 17일", "상", None),
        ("어린이날은 몇 월 며칠?", "5월 5일", "하", None),
        ("국군의 날은 몇 월 며칠?", "10월 1일", "상", None),
    ],
    "단위·숫자": [
        ("1시간은 몇 초?", 3600, "하", None),
        ("하루는 몇 분?", 1440, "중", None),
        ("한 다스(dozen)는 몇 개?", 12, "하", None),
        ("한 세기는 몇 년?", 100, "하", None),
        ("윤년의 2월은 며칠까지 있을까?", 29, "하", None),
        ("1기압에서 물이 끓는 온도는 섭씨 몇 도?", 100, "하", None),
        ("1 km는 몇 cm?", 100000, "중", None),
        ("1 L는 몇 mL?", 1000, "하", None),
        ("1 KB는 몇 바이트? (2의 거듭제곱 기준)", 1024, "중", None),
        ("1 GB는 몇 MB? (2의 거듭제곱 기준)", 1024, "중", None),
        ("2의 10제곱은?", 1024, "중", None),
        ("한 판(달걀)은 보통 몇 개?", 30, "중", None),
    ],
}


def _accepts(answer):
    """("대표 표기", "다른 표기", ...) → [대표, 다른..., 띄어쓰기 없는 대표]"""
    names = list(answer) if isinstance(answer, tuple) else [answer]
    return names + [names[0].replace(" ", "")]


def trivia(level):
    rows = [(area, row) for area, table in TRIVIA.items() for row in table if row[2] == level]
    area, (question, answer, _, wrongs) = random.choice(rows)
    if isinstance(answer, int):
        return short(f"{question} (숫자)", answer, unit=area)
    display = answer[0] if isinstance(answer, tuple) else answer
    if level == "상" and random.random() < 0.5:
        accepts = _accepts(answer)
        if area == "기념일":   # "7월 17일" 말고 "7/17" 도 정답
            month, day = (int(x) for x in re.findall(r"\d+", display))
            accepts.append(f"{month}/{day}")
        return short(question, accepts, unit=area)
    if wrongs is None:
        wrongs = [r[1][0] if isinstance(r[1], tuple) else r[1] for r in TRIVIA[area] if not isinstance(r[1], int)]
    return mc(question, display, wrongs, unit=area)


# ───────────── 사회 ─────────────
CONCEPTS = [
    ("인플레이션", "물가가 지속적으로 오르는 현상"), ("디플레이션", "물가가 지속적으로 내려가는 현상"),
    ("기회비용", "어떤 것을 선택해서 포기한 대안 중 가장 가치가 큰 것"), ("매몰 비용", "이미 지출해서 되돌릴 수 없는 비용"),
    ("독점", "한 기업이 시장의 공급을 혼자 차지하는 것"),
    ("공공재", "여러 사람이 함께 쓰고, 돈을 내지 않은 사람도 쓰지 못하게 막기 어려운 재화"),
    ("외부 효과", "어떤 경제 활동이 의도하지 않게 다른 사람에게 이익이나 손해를 주는데 대가가 오가지 않는 것"),
    ("국내 총생산(GDP)", "일정 기간 한 나라 안에서 새로 생산된 최종 생산물의 시장 가치를 합한 것"),
    ("환율", "외국 돈과 우리 돈을 바꾸는 비율"), ("누진세", "소득이 많을수록 더 높은 세율을 매기는 세금"),
    ("삼권 분립", "국가 권력을 입법·행정·사법으로 나누어 서로 견제하게 하는 것"),
    ("탄핵", "대통령 같은 고위 공무원을 국회의 소추와 헌법재판소의 심판으로 파면하는 제도"),
    ("게리맨더링", "특정 정당이나 후보에게 유리하게 선거구를 마음대로 나누는 것"),
    ("위헌 법률 심판", "법률이 헌법에 어긋나는지 헌법재판소가 판단하는 것"),
    ("헌법 소원", "공권력 때문에 기본권을 침해당한 국민이 헌법재판소에 구제를 청구하는 것"),
    ("사회 보험", "국민연금·건강 보험처럼 국가가 운영하고 가입이 의무인 보험"),
    ("공공 부조", "생활이 어려운 사람에게 국가가 비용을 부담해 최저 생활을 보장하는 제도"),
    ("님비 현상", "위험하거나 꺼리는 시설이 내 지역에 들어오는 것을 반대하는 현상"),
    ("핌피 현상", "이익이 되는 시설을 내 지역에 유치하려는 현상"),
    ("비교 우위", "다른 나라보다 더 적은 기회비용으로 생산할 수 있는 것"),
    ("수요 법칙", "다른 조건이 같을 때 가격이 오르면 수요량이 줄어드는 것"),
    ("공급 법칙", "다른 조건이 같을 때 가격이 오르면 공급량이 늘어나는 것"),
    ("고령화 사회", "전체 인구 중 65세 이상 인구가 7% 이상인 사회"),
    ("직접 민주 정치", "국민이 대표를 거치지 않고 직접 나라의 일을 결정하는 정치"),
    ("법치주의", "국가 권력은 국민의 대표가 만든 법에 따라 행사되어야 한다는 원리"),
]


def concept_mc():
    name, desc = random.choice(CONCEPTS)
    return mc(f"다음 설명에 해당하는 개념은?\n\"{desc}\"", name, [n for n, _ in CONCEPTS], unit="개념")


def concept_desc_mc():
    name, desc = random.choice(CONCEPTS)
    return mc(f"'{name}'에 대한 설명으로 옳은 것은?", desc, [d for _, d in CONCEPTS], unit="개념")


def concept_pair_wrong():
    """보기 4개 중 3개는 맞게, 1개는 틀리게 짝지어 놓는다."""
    picked = random.sample(CONCEPTS, 5)
    shown = picked[:4]
    wrong_index = random.randrange(4)
    name = shown[wrong_index][0]
    choices = [f"{n} — {d}" for n, d in shown]
    choices[wrong_index] = f"{name} — {picked[4][1]}"
    return {"q": "다음 중 개념과 설명이 바르게 짝지어지지 않은 것은?", "choices": choices,
            "answer": wrong_index + 1, "explain": f"{name}: {shown[wrong_index][1]}", "unit": "개념"}


def concept_short():
    name, desc = random.choice(CONCEPTS)
    accepts = [name, name.split("(")[0], name.replace(" ", "")]
    if "(" in name:
        accepts.append(name[name.index("(") + 1:-1])
    return short(f"다음 설명에 해당하는 개념은?\n\"{desc}\"", accepts, unit="개념")


# ───────────── 국어 ─────────────
# (맞는 표기, 틀린 표기)
SPELLING = [
    ("며칠", "몇일"), ("어이없다", "어의없다"), ("금세", "금새"), ("웬일", "왠일"), ("왠지", "웬지"),
    ("설렘", "설레임"), ("바람(희망)", "바램(희망)"), ("오랜만", "오랫만"), ("깨끗이", "깨끗히"), ("곰곰이", "곰곰히"),
    ("일일이", "일일히"), ("솔직히", "솔직이"), ("할게요", "할께요"), ("봬요", "뵈요"), ("희한하다", "희안하다"),
    ("역할", "역활"), ("대가", "댓가"), ("어떡해", "어떻해"), ("무릅쓰다", "무릎쓰다"), ("베개", "배게"),
    ("찌개", "찌게"), ("육개장", "육계장"), ("설거지", "설겆이"), ("떡볶이", "떡볶기"), ("우레", "우뢰"),
    ("개수", "갯수"), ("도긴개긴", "도찐개찐"), ("일부러", "일부로"), ("되뇌다", "되뇌이다"), ("구레나룻", "구렛나루"),
    ("움큼", "웅큼"), ("널빤지", "널판지"), ("눈살", "눈쌀"), ("얽히고설키다", "얼키고설키다"),
]
# (사자성어, 뜻)
IDIOMS = [
    ("일석이조", "한 가지 일로 두 가지 이익을 얻음"), ("고진감래", "고생 끝에 즐거움이 옴"),
    ("어부지리", "두 사람이 다투는 사이에 엉뚱한 사람이 이익을 봄"), ("사면초가", "사방이 적에게 둘러싸여 고립된 상태"),
    ("오매불망", "자나 깨나 잊지 못함"), ("결초보은", "죽어서도 잊지 않고 은혜를 갚음"),
    ("동문서답", "묻는 말에 엉뚱한 대답을 함"), ("마이동풍", "남의 말을 귀담아듣지 않고 흘려버림"),
    ("유비무환", "미리 준비해 두면 걱정할 것이 없음"), ("일취월장", "날로 달로 발전함"),
    ("자업자득", "자기가 저지른 일의 결과를 자기가 받음"), ("작심삼일", "결심한 마음이 오래가지 못함"),
    ("전화위복", "재앙이 바뀌어 오히려 복이 됨"), ("죽마고우", "어릴 때부터 함께 놀며 자란 친구"),
    ("청출어람", "제자가 스승보다 나음"), ("타산지석", "남의 하찮은 말이나 행동도 나를 닦는 데 도움이 됨"),
    ("표리부동", "겉과 속이 다름"), ("형설지공", "어려운 환경에서도 부지런히 공부함"),
    ("역지사지", "처지를 바꾸어 생각해 봄"), ("과유불급", "지나친 것은 모자란 것과 같음"),
    ("대기만성", "큰 인물은 늦게 이루어짐"), ("금상첨화", "좋은 일에 좋은 일이 더해짐"),
    ("설상가상", "어려운 일이 연달아 겹침"), ("구사일생", "죽을 고비를 여러 번 넘기고 겨우 살아남"),
    ("이심전심", "마음과 마음으로 뜻이 통함"), ("십시일반", "여러 사람이 조금씩 힘을 합치면 한 사람을 쉽게 도울 수 있음"),
    ("감언이설", "남의 비위를 맞추는 달콤한 말로 꾀는 것"), ("견물생심", "물건을 보면 갖고 싶은 마음이 생김"),
    ("우공이산", "꾸준히 노력하면 결국 큰일도 이룰 수 있음"), ("각골난망", "남에게 입은 은혜를 뼈에 새길 만큼 잊지 않음"),
]


def spelling_right():
    right, wrong = random.choice(SPELLING)
    return mc("다음 중 맞춤법이 올바른 것은?", right, [w for r, w in SPELLING if r != right],
              f"'{wrong}'(×) → '{right}'(○)", "맞춤법")


def spelling_wrong():
    right, wrong = random.choice(SPELLING)
    return mc("다음 중 맞춤법이 틀린 것은?", wrong, [r for r, _ in SPELLING if r != right],
              f"'{wrong}'(×) → '{right}'(○)", "맞춤법")


def idiom_word():
    word, meaning = random.choice(IDIOMS)
    return mc(f"'{meaning}'을 뜻하는 사자성어는?", word, [w for w, _ in IDIOMS], unit="사자성어")


def idiom_meaning():
    word, meaning = random.choice(IDIOMS)
    return mc(f"'{word}'의 뜻으로 알맞은 것은?", meaning, [m for _, m in IDIOMS], unit="사자성어")


def idiom_short():
    word, meaning = random.choice(IDIOMS)
    return short(f"'{meaning}'을 뜻하는 사자성어는? (4글자, 첫 글자: {word[0]})", word, unit="사자성어")


GENERATORS = {
    "한국사": {
        "하": [history_year_mc, history_person],
        "중": [lambda: history_order("중"), history_which_year, history_person_short],
        "상": [lambda: history_order("상"), history_year_short],
    },
    "영어": {
        "하": [english_meaning],
        "중": [english_word, english_antonym],
        "상": [english_spell],
    },
    "과학": {
        "하": [physics_easy, element_symbol],
        "중": [physics_mid, chemistry_mol, element_symbol_short],
        "상": [physics_hard, element_number],
    },
    # 분야별 사실 표(trivia)가 가장 자주 나오도록 여러 번 넣었다
    "상식": {
        "하": [lambda: capital("하"), lambda: binary_to_decimal(4)] + [lambda: trivia("하")] * 6,
        "중": [lambda: capital("중"), lambda: binary_to_decimal(7), decimal_to_binary, lambda: python_output("중")]
              + [lambda: trivia("중")] * 8,
        "상": [lambda: capital("상"), hex_convert, bitwise, lambda: python_output("상")] + [lambda: trivia("상")] * 8,
    },
    "사회": {
        "하": [concept_mc],
        "중": [concept_desc_mc, concept_mc],
        "상": [concept_short, concept_pair_wrong],
    },
    "국어": {
        "하": [spelling_right, idiom_word],
        "중": [spelling_wrong, idiom_meaning],
        "상": [idiom_short, spelling_wrong],
    },
}


def make(subject: str, level: str) -> dict | None:
    gens = GENERATORS.get(subject, {}).get(level)
    return random.choice(gens)() if gens else None
