import requests
from dotenv import load_dotenv
import os

load_dotenv()

API_KEY = os.getenv("CURRENCY_ACCESS_KEY")
BASE_URL = "http://api.exchangerate.host"

# функция для получения курсов
def get_current_rate(default: str = "USD", currencies: list[str] = ["EUR", "GBP", "JPY"]) :
    url = f"{BASE_URL}/live"
    params = {
        "access_key": API_KEY,
        "source": default,
        "currencies": ",".join(currencies)
    }

    response = requests.get(url, params=params)
    data = response.json()
    return data


# функция конвертации
def convert_currency(amount, from_currency, to_currency):
    """ Выходный данные:
    {'success': True, 'query': {'from': 'RUB', 'to': 'KZT', 'amount': 100}, 'info': {'timestamp': 1768685464, 'quote': 6.572788}, 'result': 657.2788}
    """
    url = f"{BASE_URL}/convert"
    params = {
        "access_key": API_KEY,
        "from": from_currency,
        "to": to_currency,
        "amount": amount
    }

    response = requests.get(url, params=params)
    data = response.json()
    return data

# Поддерживаемая валюта
def get_all_supported_currencies():
    url = f"{BASE_URL}/list"
    params = {
        "access_key": API_KEY,
    }
    response = requests.get(url, params=params)
    data = response.json()
    return data

# --- Хелперы для бота ---

COUNTRY_TO_CURRENCY = {
    "Russia": "RUB", "Russia (RU)": "RUB", "RU": "RUB", "РФ": "RUB", "Россия": "RUB",
    "USA": "USD", "United States": "USD", "US": "USD", "США": "USD",
    "EU": "EUR", "Europe": "EUR", "Germany": "EUR", "France": "EUR", "Italy": "EUR",
    "China": "CNY", "CN": "CNY", "Китай": "CNY",
    "Turkey": "TRY", "TR": "TRY", "Турция": "TRY",
    "Thailand": "THB", "TH": "THB", "Таиланд": "THB",
    "UAE": "AED", "AE": "AED", "ОАЭ": "AED",
    "UK": "GBP", "United Kingdom": "GBP", "GB": "GBP", "Великобритания": "GBP",
    "Kazakhstan": "KZT", "KZ": "KZT", "Казахстан": "KZT",
    "Georgia": "GEL", "GE": "GEL", "Грузия": "GEL",
    "Armenia": "AMD", "AM": "AMD", "Армения": "AMD",
}

def guess_currency(country_name):
    """
    Попытка угадать код валюты по названию страны.
    """
    return COUNTRY_TO_CURRENCY.get(country_name)

def get_exchange_rate(from_currency, to_currency):
    """
    Получает курс обмена через endpoint convert.
    """
    data = convert_currency(1, from_currency, to_currency)
    if data.get("success"):
        return data.get("info", {}).get("quote")
    return None

# Точка входа
if __name__ == "__main__":
    print(convert_currency(100,"RUB","KZT"))
