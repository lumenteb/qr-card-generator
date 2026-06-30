from dataclasses import dataclass, field
import json
import re
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as error:
    raise SystemExit(
        "Parser dependencies are missing. Install them with: pip install -r requirements"
    ) from error

from config import HTTP_USER_AGENT, REQUEST_TIMEOUT_SECONDS

REQUEST_TIMEOUT = REQUEST_TIMEOUT_SECONDS
USER_AGENT = HTTP_USER_AGENT
DEBUG = True
SIZE_PATTERN = re.compile(
    r"(?<![\d.,])"
    r"(\d{1,4}(?:[.,]\d{1,2})?)"
    r"\s*[*xX\u0445\u0425\u00d7]\s*"
    r"(\d{1,4}(?:[.,]\d{1,2})?)"
    r"(?:\s*(?:\u0441\u043c|cm|\u043c\u043c|mm))?"
    r"(?![\d.,])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProductData:
    url: str
    title: Optional[str] = None
    brand: Optional[str] = None
    country: Optional[str] = None
    product_type: Optional[str] = None
    size: Optional[str] = None
    model_name: Optional[str] = None
    price: Optional[str] = None
    image_url: Optional[str] = None
    description: Optional[str] = None
    debug_sources: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CardTextFields:
    brand_country: str
    tile_size: str
    tile_name: str

    def is_empty(self) -> bool:
        return not any((self.tile_name, self.tile_size, self.brand_country))


def debug_print(sources: Dict[str, str]) -> None:
    if not DEBUG:
        return

    print("Parser debug:")
    for field_name in ("title", "brand", "country", "product_type", "size", "model_name"):
        print(f"  {field_name}: {sources.get(field_name, 'not found')}")


def set_source(sources: Dict[str, str], field_name: str, source: str, value: Optional[str]) -> Optional[str]:
    value = clean_text(value)
    if value and field_name not in sources:
        sources[field_name] = f"{source} -> {value}"
    return value


def fetch_product_html(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "uk,en;q=0.9,ru;q=0.8"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.text


def clean_text(value) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, list):
        value = " ".join(str(item) for item in value if item)

    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def first_present(*values) -> Optional[str]:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return None


def normalize_key(key: str) -> str:
    key = clean_text(key) or ""
    key = key.lower().replace(":", "")
    key = key.replace("\u0451", "\u0435")
    return re.sub(r"[^a-z\u0430-\u044f\u0456\u0457\u0454\u04910-9]+", " ", key).strip()


def normalize_value(value: str) -> str:
    return normalize_key(value)


def key_matches(key: str, aliases: Iterable[str]) -> bool:
    normalized = normalize_key(key)
    return any(alias in normalized for alias in aliases)


def absolute_url(base_url: str, value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    try:
        from urllib.parse import urljoin

        return urljoin(base_url, value)
    except Exception:
        return value


def iter_json_objects(data):
    if isinstance(data, dict):
        yield data
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from iter_json_objects(item)
    elif isinstance(data, list):
        for item in data:
            yield from iter_json_objects(item)


def load_json_ld(soup: BeautifulSoup) -> List[dict]:
    objects = []

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw_json = script.string or script.get_text(strip=True)
        if not raw_json:
            continue

        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            continue

        objects.extend(item for item in iter_json_objects(data) if isinstance(item, dict))

    return objects


def find_json_ld_product(soup: BeautifulSoup) -> Dict:
    for item in load_json_ld(soup):
        item_type = item.get("@type")
        if isinstance(item_type, list):
            types = {str(value).lower() for value in item_type}
        else:
            types = {str(item_type).lower()}

        if "product" in types:
            return item

    return {}


def extract_meta(soup: BeautifulSoup, *names: str) -> Optional[str]:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find(
            "meta", attrs={"name": name}
        )
        if tag and tag.get("content"):
            return clean_text(tag["content"])

    return None


def extract_title(soup: BeautifulSoup, product: Dict, sources: Dict[str, str]) -> Optional[str]:
    h1 = soup.find("h1")
    if h1:
        title = set_source(sources, "title", "h1", h1.get_text(" ", strip=True))
        if title:
            return title

    title = set_source(sources, "title", "og:title", extract_meta(soup, "og:title", "twitter:title"))
    if title:
        return title

    page_title = soup.find("title")
    title = set_source(
        sources,
        "title",
        "title tag",
        page_title.get_text(" ", strip=True) if page_title else None,
    )
    if title:
        return title

    return set_source(sources, "title", "json-ld name", product.get("name"))


def extract_specs(soup: BeautifulSoup) -> Dict[str, str]:
    specs = {}

    for item in soup.select("li, div"): 
        title = item.select_one(".attr-title")
        value = item.select_one(".attr-val")
        if title and value:
            add_spec(
                specs,
                title.get_text(" ", strip=True),
                value.get_text(" ", strip=True),
            )

    for row in soup.select("table tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        add_spec(specs, cells[0].get_text(" ", strip=True), cells[1].get_text(" ", strip=True))

    for dl in soup.find_all("dl"):
        terms = dl.find_all("dt")
        definitions = dl.find_all("dd")
        for term, definition in zip(terms, definitions):
            add_spec(specs, term.get_text(" ", strip=True), definition.get_text(" ", strip=True))

    for item in soup.select(".product-info li, .product-info div, .product-info p, .characteristics li, .characteristics div, .attributes li, .attributes div, li, p"):
        text = clean_text(item.get_text(" ", strip=True))
        if not text or len(text) > 180:
            continue

        for separator in (":", "-", "–", "—"):
            if separator in text:
                key, value = text.split(separator, 1)
                add_spec(specs, key, value)
                break

    return specs


def add_spec(specs: Dict[str, str], key, value) -> None:
    key = clean_text(key)
    value = clean_text(value)
    if key and value and 2 <= len(key) <= 80 and len(value) <= 220:
        specs.setdefault(key, value)


def aliases_for(field_name: str) -> Tuple[str, ...]:
    aliases = {
        "brand": (
            "brand",
            "\u0431\u0440\u0435\u043d\u0434",
            "\u0432\u0438\u0440\u043e\u0431\u043d\u0438\u043a",
            "\u043f\u0440\u043e\u0438\u0437\u0432\u043e\u0434\u0438\u0442\u0435\u043b\u044c",
        ),
        "country": (
            "country",
            "\u043a\u0440\u0430\u0457\u043d\u0430 \u0432\u0438\u0440\u043e\u0431\u043d\u0438\u043a",
            "\u043a\u0440\u0430\u0457\u043d\u0430",
            "\u0441\u0442\u0440\u0430\u043d\u0430 \u043f\u0440\u043e\u0438\u0437\u0432\u043e\u0434\u0438\u0442\u0435\u043b\u044c",
            "\u0441\u0442\u0440\u0430\u043d\u0430",
        ),
        "product_type": (
            "type",
            "\u0442\u0438\u043f",
            "\u0432\u0438\u0434",
            "\u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0456\u044f",
            "\u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044f",
        ),
        "size": (
            "size",
            "\u0440\u043e\u0437\u043c\u0456\u0440",
            "\u0440\u0430\u0437\u043c\u0435\u0440",
            "\u0444\u043e\u0440\u043c\u0430\u0442",
        ),
        "model_name": (
            "model",
            "\u043c\u043e\u0434\u0435\u043b\u044c",
            "\u043d\u0430\u0437\u0432\u0430 \u043c\u043e\u0434\u0435\u043b\u0456",
            "\u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u043c\u043e\u0434\u0435\u043b\u0438",
            "\u043a\u043e\u043b\u0435\u043a\u0446\u0456\u044f",
            "\u043a\u043e\u043b\u043b\u0435\u043a\u0446\u0438\u044f",
        ),
    }
    return aliases[field_name]


def find_spec_value(specs: Dict[str, str], field_name: str) -> Optional[str]:
    for key, value in specs.items():
        if key_matches(key, aliases_for(field_name)):
            return clean_text(value)
    return None


def find_labeled_text(soup: BeautifulSoup, field_name: str) -> Optional[str]:
    aliases = aliases_for(field_name)
    text = clean_text(soup.get_text("\n", strip=True)) or ""
    lines = [clean_text(line) for line in text.split("\n")]
    lines = [line for line in lines if line]

    for index, line in enumerate(lines):
        normalized = normalize_key(line)
        for alias in aliases:
            if normalized == alias and index + 1 < len(lines):
                return lines[index + 1]

            if normalized.startswith(alias + " "):
                return clean_text(line[len(alias):].strip(" :-–—"))

            pattern = re.compile(rf"^{re.escape(alias)}\s*[:\-–—]\s*(.+)$", re.IGNORECASE)
            match = pattern.match(normalized)
            if match:
                return clean_text(match.group(1))

    return None


def json_ld_brand(product: Dict) -> Optional[str]:
    brand = product.get("brand")
    if isinstance(brand, dict):
        return clean_text(brand.get("name"))
    return clean_text(brand)


def extract_field_from_specs_or_text(
    soup: BeautifulSoup,
    specs: Dict[str, str],
    field_name: str,
    sources: Dict[str, str],
) -> Optional[str]:
    value = find_spec_value(specs, field_name)
    if value:
        return set_source(sources, field_name, "characteristics", value)

    value = find_labeled_text(soup, field_name)
    if value:
        return set_source(sources, field_name, "page text label", value)

    return None


def normalize_size(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    match = SIZE_PATTERN.search(value)
    if not match:
        return None

    width = match.group(1).replace(".", ",")
    height = match.group(2).replace(".", ",")
    return f"{width} x {height}"


def set_size_source(
    sources: Dict[str, str],
    source: str,
    raw_value: Optional[str],
) -> Optional[str]:
    raw_value = clean_text(raw_value)
    normalized = normalize_size(raw_value)
    if normalized and "size" not in sources:
        sources["size"] = (
            f"source: {source}; raw: {raw_value}; normalized: {normalized}"
        )
    return normalized


def find_size_in_specs(specs: Dict[str, str]) -> Optional[str]:
    for key, value in specs.items():
        if key_matches(key, aliases_for("size")) and normalize_size(value):
            return value
    return None


def json_ld_measurement_text(value) -> Optional[str]:
    if isinstance(value, dict):
        return first_present(
            value.get("value"),
            value.get("name"),
            value.get("description"),
        )
    return clean_text(value)


def extract_json_ld_size(product: Dict) -> Optional[str]:
    for key in ("size", "dimensions", "dimension"):
        value = json_ld_measurement_text(product.get(key))
        if normalize_size(value):
            return value

    width = json_ld_measurement_text(product.get("width"))
    height = json_ld_measurement_text(product.get("height"))
    combined = f"{width} x {height}" if width and height else None
    if normalize_size(combined):
        return combined

    properties = product.get("additionalProperty")
    if isinstance(properties, dict):
        properties = [properties]
    if isinstance(properties, list):
        for item in properties:
            if not isinstance(item, dict):
                continue
            label = first_present(item.get("name"), item.get("propertyID"))
            value = first_present(
                json_ld_measurement_text(item.get("value")),
                item.get("description"),
            )
            if label and key_matches(label, aliases_for("size")) and normalize_size(value):
                return value

    return None


def extract_size(
    title: Optional[str],
    specs: Dict[str, str],
    product: Dict,
    soup: BeautifulSoup,
    sources: Dict[str, str],
) -> Optional[str]:
    raw_size = find_size_in_specs(specs)
    size = set_size_source(sources, "characteristics", raw_size)
    if size:
        return size

    raw_size = extract_json_ld_size(product)
    size = set_size_source(sources, "json-ld", raw_size)
    if size:
        return size

    if title:
        match = SIZE_PATTERN.search(title)
        if match:
            size = set_size_source(sources, "title regex", match.group(0))
            if size:
                return size

    raw_size = find_labeled_text(soup, "size")
    size = set_size_source(sources, "fallback page text", raw_size)
    if size:
        return size

    return None


def extract_product_type(title: Optional[str], specs: Dict[str, str], sources: Dict[str, str]) -> Optional[str]:
    product_type = find_spec_value(specs, "product_type")
    if product_type:
        return set_source(sources, "product_type", "characteristics", product_type)

    if title:
        first_word = re.match(r"^\s*([^\s\d]+)", title)
        if first_word:
            return set_source(sources, "product_type", "first title word", first_word.group(1))

    return None


def remove_size_from_title(title: str) -> str:
    return SIZE_PATTERN.sub(" ", title)


GENERIC_PRODUCT_TYPE_PATTERNS = (
    r"\u043a\u0435\u0440\u0430\u043c\u0456\u0447\u043d\u0430\s+\u043f\u043b\u0438\u0442\u043a\u0430",
    r"\u043d\u0430\u0441\u0442\u0456\u043d\u043d\u0430\s+\u043f\u043b\u0438\u0442\u043a\u0430",
    r"\u043f\u0456\u0434\u043b\u043e\u0433\u043e\u0432\u0430\s+\u043f\u043b\u0438\u0442\u043a\u0430",
    r"\u043f\u043b\u0438\u0442\u043a\u0430",
    r"\u0434\u0435\u043a\u043e\u0440",
    r"\u043a\u0435\u0440\u0430\u043c\u043e\u0433\u0440\u0430\u043d\u0456\u0442",
    r"\u043a\u0435\u0440\u0430\u043c\u043e\u0433\u0440\u0430\u043d\u0438\u0442",
    r"tile",
    r"plitka",
    r"decor",
    r"dekor",
)


def normalize_model_name(value: Optional[str], product_type: Optional[str] = None, size: Optional[str] = None) -> Optional[str]:
    model = clean_text(value)
    if not model:
        return None

    model = remove_size_from_title(model)

    if size:
        model = re.sub(re.escape(size), " ", model, flags=re.IGNORECASE)
        model = re.sub(re.escape(size.replace(" ", "")), " ", model, flags=re.IGNORECASE)

    prefixes = list(GENERIC_PRODUCT_TYPE_PATTERNS)
    if product_type:
        prefixes.insert(0, re.escape(product_type))

    for pattern in prefixes:
        model = re.sub(rf"^\s*{pattern}\b", " ", model, flags=re.IGNORECASE)

    return clean_text(model)


def extract_model_name(
    title: Optional[str],
    product_type: Optional[str],
    size: Optional[str],
    specs: Dict[str, str],
    product: Dict,
    sources: Dict[str, str],
) -> Optional[str]:
    model = normalize_model_name(title, product_type, size)
    if model and model != clean_text(title):
        return set_source(sources, "model_name", "title minus type and size", model)

    explicit_model = first_present(find_spec_value(specs, "model_name"), product.get("model"))
    model = normalize_model_name(explicit_model, product_type, size)
    if model:
        return set_source(sources, "model_name", "explicit model normalized", model)

    return None


def extract_price(product: Dict, soup: BeautifulSoup) -> Optional[str]:
    offers = product.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None

    if isinstance(offers, dict):
        price = first_present(offers.get("price"), offers.get("lowPrice"))
        currency = clean_text(offers.get("priceCurrency"))
        if price and currency:
            return f"{price} {currency}"
        if price:
            return price

    return extract_meta(soup, "product:price:amount", "og:price:amount")


def extract_image(base_url: str, product: Dict, soup: BeautifulSoup) -> Optional[str]:
    image = product.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    elif isinstance(image, dict):
        image = image.get("url")

    return absolute_url(
        base_url,
        first_present(image, extract_meta(soup, "og:image", "twitter:image")),
    )


def extract_description(soup: BeautifulSoup, product: Dict) -> Optional[str]:
    return first_present(
        product.get("description"),
        extract_meta(soup, "description", "og:description", "twitter:description"),
    )


def parse_product_page(url: str) -> ProductData:
    html = fetch_product_html(url)
    soup = BeautifulSoup(html, "html.parser")
    product = find_json_ld_product(soup)
    specs = extract_specs(soup)
    sources: Dict[str, str] = {}

    title = extract_title(soup, product, sources)

    brand = extract_field_from_specs_or_text(soup, specs, "brand", sources)
    if not brand:
        brand = set_source(sources, "brand", "json-ld brand", json_ld_brand(product))

    country = extract_field_from_specs_or_text(soup, specs, "country", sources)
    product_type = extract_product_type(title, specs, sources)
    size = extract_size(title, specs, product, soup, sources)
    model_name = extract_model_name(title, product_type, size, specs, product, sources)

    debug_print(sources)

    return ProductData(
        url=url,
        title=title,
        brand=brand,
        country=country,
        product_type=product_type,
        size=size,
        model_name=model_name,
        price=extract_price(product, soup),
        image_url=extract_image(url, product, soup),
        description=extract_description(soup, product),
        debug_sources=sources,
    )


def build_card_text_fields(product: ProductData) -> CardTextFields:
    if product.brand and product.country:
        brand_country = f"{product.brand} ({product.country})"
    elif product.brand:
        brand_country = product.brand
    elif product.country:
        brand_country = f"({product.country})"
    else:
        brand_country = ""

    model_name = normalize_model_name(product.model_name or product.title, product.product_type, product.size)
    return CardTextFields(
        brand_country=brand_country,
        tile_size=product.size or "",
        tile_name=model_name or "",
    )


def format_card_preview(product: ProductData) -> CardTextFields:
    """Backward-compatible name for the structured card text builder."""
    return build_card_text_fields(product)
