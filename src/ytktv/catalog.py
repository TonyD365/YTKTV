"""What a KTV song book knows offline: artists by language and type, classic songs, and
pinyin initials, so "ydsl" finds 月亮代表我的心 like on a real KTV machine."""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

LANGUAGES = ("Mandarin", "Cantonese", "English", "Japanese", "Korean")
KINDS = ("Male", "Female", "Group")

# (name, language, kind)
ARTISTS: tuple[tuple[str, str, str], ...] = (
    ("周杰倫", "Mandarin", "Male"),
    ("林俊傑", "Mandarin", "Male"),
    ("王力宏", "Mandarin", "Male"),
    ("李榮浩", "Mandarin", "Male"),
    ("薛之謙", "Mandarin", "Male"),
    ("毛不易", "Mandarin", "Male"),
    ("周深", "Mandarin", "Male"),
    ("任賢齊", "Mandarin", "Male"),
    ("陶喆", "Mandarin", "Male"),
    ("鄧紫棋", "Mandarin", "Female"),
    ("張惠妹", "Mandarin", "Female"),
    ("蔡依林", "Mandarin", "Female"),
    ("孫燕姿", "Mandarin", "Female"),
    ("田馥甄", "Mandarin", "Female"),
    ("張韶涵", "Mandarin", "Female"),
    ("鄧麗君", "Mandarin", "Female"),
    ("梁靜茹", "Mandarin", "Female"),
    ("五月天", "Mandarin", "Group"),
    ("告五人", "Mandarin", "Group"),
    ("S.H.E", "Mandarin", "Group"),
    ("蘇打綠", "Mandarin", "Group"),
    ("F4", "Mandarin", "Group"),
    ("陳奕迅", "Cantonese", "Male"),
    ("張學友", "Cantonese", "Male"),
    ("古巨基", "Cantonese", "Male"),
    ("李克勤", "Cantonese", "Male"),
    ("謝霆鋒", "Cantonese", "Male"),
    ("林家謙", "Cantonese", "Male"),
    ("姜濤", "Cantonese", "Male"),
    ("劉德華", "Cantonese", "Male"),
    ("張國榮", "Cantonese", "Male"),
    ("容祖兒", "Cantonese", "Female"),
    ("楊千嬅", "Cantonese", "Female"),
    ("鄭秀文", "Cantonese", "Female"),
    ("王菲", "Cantonese", "Female"),
    ("梅艷芳", "Cantonese", "Female"),
    ("衛蘭", "Cantonese", "Female"),
    ("Beyond", "Cantonese", "Group"),
    ("MIRROR", "Cantonese", "Group"),
    ("Twins", "Cantonese", "Group"),
    ("Ed Sheeran", "English", "Male"),
    ("Bruno Mars", "English", "Male"),
    ("Michael Jackson", "English", "Male"),
    ("Elton John", "English", "Male"),
    ("Taylor Swift", "English", "Female"),
    ("Adele", "English", "Female"),
    ("Lady Gaga", "English", "Female"),
    ("Billie Eilish", "English", "Female"),
    ("Whitney Houston", "English", "Female"),
    ("Celine Dion", "English", "Female"),
    ("Coldplay", "English", "Group"),
    ("Queen", "English", "Group"),
    ("The Beatles", "English", "Group"),
    ("ABBA", "English", "Group"),
    ("Maroon 5", "English", "Group"),
    ("Backstreet Boys", "English", "Group"),
    ("Bon Jovi", "English", "Group"),
    ("米津玄師", "Japanese", "Male"),
    ("藤井風", "Japanese", "Male"),
    ("優里", "Japanese", "Male"),
    ("Vaundy", "Japanese", "Male"),
    ("あいみょん", "Japanese", "Female"),
    ("宇多田ヒカル", "Japanese", "Female"),
    ("中島美嘉", "Japanese", "Female"),
    ("Ado", "Japanese", "Female"),
    ("LiSA", "Japanese", "Female"),
    ("YOASOBI", "Japanese", "Group"),
    ("Official髭男dism", "Japanese", "Group"),
    ("嵐", "Japanese", "Group"),
    ("back number", "Japanese", "Group"),
    ("King Gnu", "Japanese", "Group"),
    ("Mrs. GREEN APPLE", "Japanese", "Group"),
    ("スピッツ", "Japanese", "Group"),
    ("PSY", "Korean", "Male"),
    ("Jung Kook", "Korean", "Male"),
    ("IU", "Korean", "Female"),
    ("TAEYEON", "Korean", "Female"),
    ("BTS", "Korean", "Group"),
    ("BLACKPINK", "Korean", "Group"),
    ("TWICE", "Korean", "Group"),
    ("NewJeans", "Korean", "Group"),
    ("EXO", "Korean", "Group"),
    ("BIGBANG", "Korean", "Group"),
    ("SEVENTEEN", "Korean", "Group"),
    ("aespa", "Korean", "Group"),
    ("Stray Kids", "Korean", "Group"),
    ("Red Velvet", "Korean", "Group"),
    ("LE SSERAFIM", "Korean", "Group"),
)

# Classic KTV songs: (title, artist). Searching YouTube for "artist title" finds them.
SONGS: tuple[tuple[str, str], ...] = (
    ("月亮代表我的心", "鄧麗君"),
    ("甜蜜蜜", "鄧麗君"),
    ("我只在乎你", "鄧麗君"),
    ("小城故事", "鄧麗君"),
    ("晴天", "周杰倫"),
    ("七里香", "周杰倫"),
    ("稻香", "周杰倫"),
    ("告白氣球", "周杰倫"),
    ("青花瓷", "周杰倫"),
    ("簡單愛", "周杰倫"),
    ("夜曲", "周杰倫"),
    ("說好的幸福呢", "周杰倫"),
    ("江南", "林俊傑"),
    ("修煉愛情", "林俊傑"),
    ("不為誰而作的歌", "林俊傑"),
    ("可惜沒如果", "林俊傑"),
    ("她說", "林俊傑"),
    ("光年之外", "鄧紫棋"),
    ("泡沫", "鄧紫棋"),
    ("句號", "鄧紫棋"),
    ("倔強", "五月天"),
    ("突然好想你", "五月天"),
    ("知足", "五月天"),
    ("溫柔", "五月天"),
    ("後來", "劉若英"),
    ("聽海", "張惠妹"),
    ("我可以抱你嗎", "張惠妹"),
    ("日不落", "蔡依林"),
    ("天黑黑", "孫燕姿"),
    ("遇見", "孫燕姿"),
    ("綠光", "孫燕姿"),
    ("小幸運", "田馥甄"),
    ("你就不要想起我", "田馥甄"),
    ("隱形的翅膀", "張韶涵"),
    ("歐若拉", "張韶涵"),
    ("心太軟", "任賢齊"),
    ("對面的女孩看過來", "任賢齊"),
    ("演員", "薛之謙"),
    ("醜八怪", "薛之謙"),
    ("消愁", "毛不易"),
    ("像我這樣的人", "毛不易"),
    ("大魚", "周深"),
    ("年少有為", "李榮浩"),
    ("模特", "李榮浩"),
    ("唯一", "王力宏"),
    ("大城小愛", "王力宏"),
    ("勇氣", "梁靜茹"),
    ("寧夏", "梁靜茹"),
    ("愛很簡單", "陶喆"),
    ("Super Star", "S.H.E"),
    ("戀愛ing", "五月天"),
    ("流星雨", "F4"),
    ("小情歌", "蘇打綠"),
    ("愛情轉移", "陳奕迅"),
    ("十年", "陳奕迅"),
    ("富士山下", "陳奕迅"),
    ("浮誇", "陳奕迅"),
    ("K歌之王", "陳奕迅"),
    ("好久不見", "陳奕迅"),
    ("吻別", "張學友"),
    ("一千個傷心的理由", "張學友"),
    ("每天愛你多一些", "張學友"),
    ("海闊天空", "Beyond"),
    ("真的愛你", "Beyond"),
    ("光輝歲月", "Beyond"),
    ("喜歡你", "Beyond"),
    ("紅日", "李克勤"),
    ("月半小夜曲", "李克勤"),
    ("情非得已", "庾澄慶"),
    ("忘情水", "劉德華"),
    ("冰雨", "劉德華"),
    ("恭喜發財", "劉德華"),
    ("紅豆", "王菲"),
    ("傳奇", "王菲"),
    ("容易受傷的女人", "王菲"),
    ("夕陽之歌", "梅艷芳"),
    ("女人花", "梅艷芳"),
    ("風繼續吹", "張國榮"),
    ("當年情", "張國榮"),
    ("少女的祈禱", "楊千嬅"),
    ("小城大事", "楊千嬅"),
    ("揮著翅膀的女孩", "容祖兒"),
    ("我的驕傲", "容祖兒"),
    ("連鎖反應", "Twins"),
    ("老鼠愛大米", "楊臣剛"),
    ("最炫民族風", "鳳凰傳奇"),
    ("朋友", "周華健"),
    ("萍聚", "李翊君"),
    ("童話", "光良"),
    ("第一次", "光良"),
    ("那些年", "胡夏"),
    ("小酒窩", "林俊傑"),
    ("屋頂", "周杰倫"),
    ("知足常樂", "汪蘇瀧"),
    ("成都", "趙雷"),
    ("南山南", "馬頔"),
    ("平凡之路", "樸樹"),
    ("生日快樂", "Happy Birthday"),
    ("Let It Be", "The Beatles"),
    ("Hey Jude", "The Beatles"),
    ("Yesterday", "The Beatles"),
    ("Bohemian Rhapsody", "Queen"),
    ("We Are the Champions", "Queen"),
    ("Dancing Queen", "ABBA"),
    ("Mamma Mia", "ABBA"),
    ("My Heart Will Go On", "Celine Dion"),
    ("I Will Always Love You", "Whitney Houston"),
    ("Someone Like You", "Adele"),
    ("Rolling in the Deep", "Adele"),
    ("Shape of You", "Ed Sheeran"),
    ("Perfect", "Ed Sheeran"),
    ("Just the Way You Are", "Bruno Mars"),
    ("Uptown Funk", "Bruno Mars"),
    ("Shallow", "Lady Gaga"),
    ("Yellow", "Coldplay"),
    ("Viva la Vida", "Coldplay"),
    ("I Want It That Way", "Backstreet Boys"),
    ("Livin' on a Prayer", "Bon Jovi"),
    ("Billie Jean", "Michael Jackson"),
    ("Your Song", "Elton John"),
    ("Love Story", "Taylor Swift"),
    ("Shake It Off", "Taylor Swift"),
    ("Sugar", "Maroon 5"),
    ("Gangnam Style", "PSY"),
    ("Dynamite", "BTS"),
    ("夜に駆ける", "YOASOBI"),
    ("Lemon", "米津玄師"),
    ("雪の華", "中島美嘉"),
)


@lru_cache(maxsize=4096)
def initials(text: str) -> str:
    """The first letter of every Chinese character's pinyin and of every other word.

    "月亮代表我的心" -> "yldbwdx", "Let It Be" -> "lib". Japanese kana and other scripts
    are skipped.
    """
    from pypinyin import Style, lazy_pinyin

    letters = []
    for part in lazy_pinyin(text, style=Style.FIRST_LETTER, errors=lambda s: s):
        for word in re.findall(r"[A-Za-z0-9]+", part):
            letters.append(word[0].lower())
    return "".join(letters)


def looks_like_initials(query: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z]{2,10}", query.strip()))


def match_initials(query: str, more: Iterable[tuple[str, str]] = (), limit: int = 12) -> list[str]:
    """Songs whose title's initials start with *query*, as "title - artist" search texts.

    *more* adds (title, artist) pairs the room already knows: favorites, history.
    """
    query = query.strip().lower()
    if not looks_like_initials(query):
        return []
    found: list[str] = []
    seen: set[str] = set()
    for title, artist in (*tuple(more), *SONGS):
        if title in seen:
            continue
        if initials(title).startswith(query):
            seen.add(title)
            found.append(f"{title} - {artist}" if artist else title)
        if len(found) >= limit:
            break
    return found


def artists(language: str = "", kind: str = "") -> list[str]:
    return [
        n
        for n, lang, k in ARTISTS
        if (not language or lang == language) and (not kind or k == kind)
    ]
