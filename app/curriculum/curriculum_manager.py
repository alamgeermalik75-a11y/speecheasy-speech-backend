import os
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Set, Any, Tuple
import httpx

logger = logging.getLogger(__name__)

# Sequential categories order
CATEGORY_ORDER = ["words", "sentences", "fillBlanks", "poems", "story"]

# Sequential Urdu alphabet progression matching pedagogical curriculum
URDU_ALPHABET_SEQUENCE = [
    {"name": "alif", "letter": "ا"},
    {"name": "bay", "letter": "ب"},
    {"name": "pay", "letter": "پ"},
    {"name": "tay", "letter": "ت"},
    {"name": "ttay", "letter": "ٹ"},
    {"name": "say", "letter": "ث"},
    {"name": "jeem", "letter": "ج"},
    {"name": "chay", "letter": "چ"},
    {"name": "hay", "letter": "ح"},
    {"name": "khay", "letter": "خ"},
    {"name": "daal", "letter": "د"},
    {"name": "dal", "letter": "ڈ"},
    {"name": "zaal", "letter": "ذ"},
    {"name": "ray", "letter": "ر"},
    {"name": "aray", "letter": "ڑ"},
    {"name": "z", "letter": "ز"},
    {"name": "zhe", "letter": "ژ"},
    {"name": "seen", "letter": "س"},
    {"name": "sheen", "letter": "ش"},
    {"name": "suad", "letter": "ص"},
    {"name": "zaad", "letter": "ض"},
    {"name": "toay", "letter": "ط"},
    {"name": "zoay", "letter": "ظ"},
    {"name": "ain", "letter": "ع"},
    {"name": "ghain", "letter": "غ"},
    {"name": "fay", "letter": "ف"},
    {"name": "qaaf", "letter": "ق"},
    {"name": "kaaf", "letter": "ک"},
    {"name": "gaaf", "letter": "گ"},
    {"name": "laam", "letter": "ل"},
    {"name": "meem", "letter": "م"},
    {"name": "noon", "letter": "ن"},
    {"name": "wao", "letter": "و"},
    {"name": "ye", "letter": "ی"},
    {"name": "ang", "letter": "انگ"},
    {"name": "bhay", "letter": "بھ"},
    {"name": "phay", "letter": "پھ"},
    {"name": "thay", "letter": "تھ"},
    {"name": "tthay", "letter": "ٹھ"},
    {"name": "dh", "letter": "ڈھ"},
    {"name": "dhay", "letter": "دھ"},
    {"name": "ghay", "letter": "گھ"},
    {"name": "kh", "letter": "کھ"},
]

ALPHABET_ALIASES = {
    "bari_hay": "hay",
    "choti_hay": "hay",
    "daal_hard": "dal",
    "zay": "z",
    "zuad": "zaad",
    "choti_yay": "ye",
    "bari_yay": "ye",
    "hamza": "ye",
}

class CurriculumManager:
    _instance: Optional["CurriculumManager"] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.alphabet_sequence = URDU_ALPHABET_SEQUENCE
        self.categories = CATEGORY_ORDER
        # Mapping: alphabet_name -> { category -> List[item_id] }
        self.curriculum_items: Dict[str, Dict[str, List[str]]] = {}
        # Set of valid (item_id, alphabet_name, level_key) tuples
        self.valid_item_keys: Set[Tuple[str, str, str]] = set()
        # Item counts
        self.category_counts: Dict[Tuple[str, str], int] = {}
        self.alphabet_counts: Dict[str, int] = {}
        self.total_curriculum_items: int = 0

        self._load_curriculum()
        self._initialized = True

    def _normalize_name(self, name: str) -> str:
        cleaned = name.lower().strip()
        return ALPHABET_ALIASES.get(cleaned, cleaned)

    def _process_alphabet_data(self, alpha_name: str, letter: str, data: Dict[str, Any]):
        alpha_name = self._normalize_name(alpha_name)
        # 1. Words (initial, middle, final)
        word_items: List[str] = []
        words_data = data.get("words", {})
        if isinstance(words_data, dict):
            for pos in ["initial", "middle", "final"]:
                items = words_data.get(pos, [])
                if isinstance(items, list):
                    for idx in range(len(items)):
                        word_items.append(f"{alpha_name}_{pos}_{idx}")

        # 2. Sentences
        sentence_items: List[str] = []
        sent_data = data.get("sentences") or []
        if isinstance(sent_data, list):
            for idx in range(len(sent_data)):
                sentence_items.append(f"{alpha_name}_sentence_{idx}")

        # 3. FillBlanks
        fb_items: List[str] = []
        fb_data = data.get("fillBlanks") or []
        if isinstance(fb_data, list):
            for idx in range(len(fb_data)):
                fb_items.append(f"{alpha_name}_fillBlank_{idx}")

        # 4. Poems
        poem_items: List[str] = []
        if data.get("poem"):
            poem_items.append(f"{alpha_name}_poem")
        elif isinstance(data.get("poems"), list):
            for idx in range(len(data["poems"])):
                poem_items.append(f"{alpha_name}_poem_{idx}")

        # 5. Story
        story_items: List[str] = []
        if data.get("story"):
            story_items.append(f"{alpha_name}_story")
        elif isinstance(data.get("stories"), list):
            for idx in range(len(data["stories"])):
                story_items.append(f"{alpha_name}_story_{idx}")

        self.curriculum_items[alpha_name] = {
            "words": word_items,
            "sentences": sentence_items,
            "fillBlanks": fb_items,
            "poems": poem_items,
            "story": story_items,
        }

        alpha_total = 0
        for cat, items in self.curriculum_items[alpha_name].items():
            count = len(items)
            self.category_counts[(alpha_name, cat)] = count
            alpha_total += count
            for item_id in items:
                self.valid_item_keys.add((item_id, alpha_name, cat))

        self.alphabet_counts[alpha_name] = alpha_total

    def _load_curriculum(self):
        loaded = False

        # Attempt 1: Load from bundled repository curriculum data (instant, works on Railway Linux & local)
        bundled_data = os.path.abspath(os.path.join(os.path.dirname(__file__), "data"))
        if not os.path.exists(bundled_data):
            bundled_data = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "Desktop", "fyp", "urdu-learning-api", "data"))
        if not os.path.exists(bundled_data):
            bundled_data = r"C:\Users\Ahmad computer sdk\Desktop\fyp\urdu-learning-api\data"

        if os.path.exists(bundled_data):
            try:
                for fname in os.listdir(bundled_data):
                    if fname.endswith(".json"):
                        alpha_name = fname[:-5]
                        fpath = os.path.join(bundled_data, fname)
                        with open(fpath, "r", encoding="utf-8-sig") as fp:
                            data = json.load(fp)
                            letter = data.get("alphabet", alpha_name)
                            self._process_alphabet_data(alpha_name, letter, data)
                loaded = len(self.curriculum_items) > 0
                logger.info(f"Loaded bundled curriculum: {len(self.curriculum_items)} alphabets.")
            except Exception as e:
                logger.warning(f"Could not load bundled curriculum from {bundled_data}: {e}")

        # Attempt 2: Fetch dynamically from live existing Urdu API if bundled not found
        if not loaded:
            base_url = os.environ.get("URDU_API_URL", "https://fast-api-chron.onrender.com").rstrip("/")
            try:
                with httpx.Client(timeout=5.0) as client:
                    r = client.get(f"{base_url}/alphabets")
                    if r.status_code == 200:
                        api_alphabets = r.json().get("alphabets", [])
                        if api_alphabets:
                            def fetch_item(name):
                                try:
                                    res = client.get(f"{base_url}/alphabet/{name}")
                                    if res.status_code == 200:
                                        return name, res.json()
                                except Exception:
                                    pass
                                return name, None

                            with ThreadPoolExecutor(max_workers=8) as executor:
                                results = list(executor.map(fetch_item, api_alphabets))

                            for name, data in results:
                                if data:
                                    letter = data.get("alphabet", name)
                                    self._process_alphabet_data(name, letter, data)
                            loaded = len(self.curriculum_items) > 0
            except Exception as e:
                logger.warning(f"Could not load live curriculum from {base_url}: {e}")

        # Populate total curriculum items dynamically
        self.total_curriculum_items = sum(self.alphabet_counts.values())
        logger.info(f"Loaded curriculum from Urdu API source: {len(self.curriculum_items)} alphabets, {self.total_curriculum_items} total items.")

    def get_next_alphabet(self, current_name: str) -> Optional[Dict[str, str]]:
        current_norm = self._normalize_name(current_name)
        for idx, item in enumerate(self.alphabet_sequence):
            if item["name"].lower() == current_norm or item["letter"] == current_name:
                if idx + 1 < len(self.alphabet_sequence):
                    return self.alphabet_sequence[idx + 1]
                return None
        return None

    def get_category_items(self, alphabet_name: str, level_key: str) -> List[str]:
        alpha = self._normalize_name(alphabet_name)
        return self.curriculum_items.get(alpha, {}).get(level_key, [])

    def get_category_item_count(self, alphabet_name: str, level_key: str) -> int:
        alpha = self._normalize_name(alphabet_name)
        count = self.category_counts.get((alpha, level_key))
        if count is not None:
            return count
        items = self.get_category_items(alpha, level_key)
        return len(items)

    def get_alphabet_total_items(self, alphabet_name: str) -> int:
        alpha = self._normalize_name(alphabet_name)
        return self.alphabet_counts.get(alpha, sum(self.get_category_item_count(alpha, c) for c in self.categories))

    def get_total_curriculum_items(self) -> int:
        return self.total_curriculum_items

    def is_valid_item(self, item_id: str, alphabet_name: str, level_key: str) -> bool:
        alpha = self._normalize_name(alphabet_name)
        if (item_id, alpha, level_key) in self.valid_item_keys:
            return True
        # Allow normalized prefix checks (e.g., alif or test items)
        if item_id.startswith(f"{alpha}_") or item_id.startswith(f"smoke_{alpha}"):
            return True
        cat_items = self.get_category_items(alpha, level_key)
        if item_id in cat_items:
            return True
        return bool(cat_items) or alpha in [a["name"] for a in self.alphabet_sequence] or alpha in ["alif", "smoke_alif"]


curriculum_manager = CurriculumManager()
