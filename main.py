import langgraph.graph.state
import telebot
from telebot import types
from telebot.util import quick_markup
import requests
from agent import agent_executor
from model_giga import get_state_graph, call_model, create_memory_saver, get_list_input_message
from model_giga import MESSAGES, START, SystemMessage, HumanMessage

from dotenv import load_dotenv
import os

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
API_KEY_OPEN_WEATHER = os.getenv("API_KEY_OPEN_WEATHER_MAP")

START_MESSAGE = ("Я бот, в котором можно узнать погоду и об интересных местах!\n"
                 "Что выберешь?")
BUTTON_WEATHER_TEXT = "🌤 Узнать погоду"
BUTTON_START_DIALOG_TEXT = "💬 Начать диалог с ассистентом, чтобы узнать об интересных местах"
BUTTON_END_DIALOG_TEXT = "❌ Закончить диалог"
CALLBACK_DATA_WEATHER = "weather"
CALLBACK_DATA_START_DIALOG_AI = "dialog_ai_start"
CALLBACK_DATA_END_DIALOG_AI = "dialog_ai_end"
BUTTONS_START = {
    BUTTON_WEATHER_TEXT: {"callback_data": CALLBACK_DATA_WEATHER},
    BUTTON_START_DIALOG_TEXT: {"callback_data": CALLBACK_DATA_START_DIALOG_AI}
}
BUTTON_END_DIALOG_AI = {
    BUTTON_END_DIALOG_TEXT: {"callback_data": CALLBACK_DATA_END_DIALOG_AI}
}
DIALOG_AI_MESSAGE_START_TEXT = "Диалог с ассистентом начался. Напишите сообщение!"
FLAG_AI_DIALOG_SESSION = "is_in_dialog"
DIALOG_AI_MESSAGE_END_TEXT = "Диалог с ассистентом завершён."
BUTTON_WEATHER_AGENT_TEXT = "Узнать погоду в этом месте"
CALLBACK_DATA_WEATHER_AGENT = "agent_weather"
BUTTON_WEATHER_AGENT = {
    BUTTON_WEATHER_AGENT_TEXT: {"callback_data": CALLBACK_DATA_WEATHER_AGENT}
}
AGENT_HUMAN_MESSAGE = "Проанализируй следующую информацию, если там идёт речь о како-либо городе или месте, то используй функцию поиска Tavily, чтобы кратко рассказать о погоде в этом месте." \
                      "Обычно в этом тексте будет информация о достопримечательностях, которые есть в этом месте." \
                      "Текст: "
ERROR_REQUEST_AGENT_TEXT = "У агента не получилось обработать запрос ("
ERROR_REQUEST_AI_TEXT = "У ассистента не получилось обработать запрос ("
TEXT_FOR_CHOICE_LOCATION_WEATHER = ("Выберете, где хотите узнать погоду.\n"
                                    "Если хотите узнать погоду в любой локации, введите её название")
TEXT_BUTTON_USER_LOCATION_WEATHER = "Узнать погоду в своём местоположении"
TEXT_ERROR_REQUEST_WEATHER = "Упс... Получить погоду не получилось..."
CHARACTERISTICS_WEATHER = ["Погода в", "Погода", "Температура ℃", "Ощущается как ℃", "Скорость ветра м/с"]
HELP_TEXT = ("ИИ-ассистент на базе Gigachat\n"
             "Рассказывает о интересных местах в различных городах, а также сообщает состояние погоды с помощью сервиса OpenWeatherMap и ИИ-агента, который умеет искать информацию о погоде, используя сервис Tavily.\n"
             "Команды:\n"
             "/start - Начать диалог с ботом\n"
             "/help - Вывод помощи\n"
             "/weather - Узнать погоду с помощью OpenWeatherMap\n"
             "/menu - меню команд")
MENU_TEXT = "Меню"
LLM_MODEL = "giga"
APP = "app"
MEMORY = "memory"

chat_sessions = {}

bot = telebot.TeleBot(token=TOKEN)


@bot.message_handler(commands=['start'])
def get_start_message(message: types.Message):
    """
    Функция начала диалога
    """
    chat_id = get_chat_id(message)
    if checking_ai_dialog(chat_id):
        start_keyboard = get_inline_keyboard(buttons=BUTTONS_START)
        bot.send_message(chat_id=chat_id, text=f"{START_MESSAGE}", reply_markup=start_keyboard)


def get_inline_keyboard(buttons: dict[str:dict]) -> types.InlineKeyboardMarkup:
    keyboard = quick_markup(values=buttons, row_width=1)
    return keyboard


def get_chat_id(message: types.Message):
    return message.chat.id


@bot.message_handler(commands=['help'])
def get_help(message: types.Message):
    """
    Функция справки
    """
    chat_id = get_chat_id(message)
    if checking_ai_dialog(chat_id):
        bot.send_message(chat_id=chat_id, text=f"{HELP_TEXT}")


@bot.message_handler(commands=["menu"])
def get_menu(message: types.Message):
    chat_id = get_chat_id(message)
    if checking_ai_dialog(chat_id):
        keyboard_menu = get_inline_keyboard(buttons=BUTTONS_START)
        bot.send_message(chat_id, MENU_TEXT, reply_markup=keyboard_menu)


def start_weather(chat_id):
    """
    Обработка первого шага получения погоды пользователем
    """
    keyboard_user_location = get_keyboard_location()
    bot.send_message(text=TEXT_FOR_CHOICE_LOCATION_WEATHER, chat_id=chat_id,
                     reply_markup=keyboard_user_location)
    bot.register_next_step_handler_by_chat_id(chat_id=chat_id, callback=handle_city_input)


@bot.callback_query_handler(func=lambda call: call.data == CALLBACK_DATA_WEATHER)
def get_weather(call: types.CallbackQuery):
    """
    Обработка обратного вызова для кнопки погоды
    """
    chat_id = get_chat_id_from_call(call)
    message_id = get_message_id_from_call(call)
    bot.edit_message_reply_markup(chat_id, message_id)
    start_weather(chat_id)


def get_chat_id_from_call(call: types.CallbackQuery):
    return call.message.chat.id


def get_message_id_from_call(call: types.CallbackQuery):
    return call.message.message_id


def get_keyboard_location() -> types.ReplyKeyboardMarkup:
    """
    Создание клавиатуры для отправки геолокации пользователем
    """
    button_request_location = types.KeyboardButton(text=TEXT_BUTTON_USER_LOCATION_WEATHER,
                                                   request_location=True)
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add(button_request_location)
    return keyboard


@bot.message_handler(commands=["weather"])
def get_weather_fron_msg(message: types.Message):
    """
    Обработка команды /weather
    """
    chat_id = message.chat.id
    if checking_ai_dialog(chat_id):
        start_weather(chat_id)


@bot.message_handler(content_types=['location'])
def handle_location(message: types.Message):
    """
    Работа с геопозицией пользователя
    """
    chat_id = get_chat_id(message)
    latitude, longitude = get_coords_location(message)
    response = request_current_weather_data(latitude=latitude, longitude=longitude)
    if not response:
        bot.send_message(chat_id=chat_id, text=TEXT_ERROR_REQUEST_WEATHER,
                         reply_markup=types.ReplyKeyboardRemove())
    else:
        current_weather = get_current_weather(response)
        description_weather = get_text_description_weather(current_weather[:-1])
        bot.send_photo(chat_id=chat_id, photo=f"https://openweathermap.org/img/wn/{current_weather[-1]}@4x.png",
                       caption=description_weather, parse_mode="html", reply_markup=types.ReplyKeyboardRemove())
    bot.clear_step_handler_by_chat_id(chat_id=chat_id)


def get_coords_location(message: types.Message) -> tuple[float, float]:
    lat = message.location.latitude
    lon = message.location.longitude
    return lat, lon


def request_current_weather_data(latitude=None, longitude=None, city_name=None) -> None | dict:
    """
    Запрос к сервису опен визер
    """
    try:
        if city_name is None:
            response = requests.get(
                f"https://api.openweathermap.org/data/2.5/weather?lat={latitude}&lon={longitude}&appid={API_KEY_OPEN_WEATHER}&units=metric&lang=ru",
                timeout=10)
        else:
            response = requests.get(
                f"https://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={API_KEY_OPEN_WEATHER}&units=metric&lang=ru",
                timeout=10)
    except requests.exceptions.RequestException:
        return None
    else:
        if response.status_code == 200:
            return response.json()
        else:
            return None


def get_current_weather(data: dict) -> tuple:
    """
    Получение данных о текущей погоде
    """
    name_loc = data.get("name")
    weather = data.get("weather")[0]
    weather_desc = weather.get("description")
    weather_main = data.get("main")
    weather_temp = weather_main.get("temp")
    weather_feels_like = weather_main.get("feels_like")
    weather_wind = data.get("wind")
    weather_wind_speed = weather_wind.get("speed")
    weather_icon = weather.get("icon")
    return name_loc, weather_desc, weather_temp, weather_feels_like, weather_wind_speed, weather_icon


def get_text_description_weather(weather: tuple | list) -> str:
    """
    Формирование строки описания погоды
    """
    text = ""
    for character, value in zip(CHARACTERISTICS_WEATHER, weather):
        text += f"{character}: <b>{value}</b>\n"
    return text


def handle_city_input(message: types.Message):
    """
    Обработка ввода города или геопозиции
    """
    if message.content_type == "location":
        handle_location(message)
    elif message.content_type == "text":
        handle_weather_city(message)


def handle_weather_city(message: types.Message):
    """
    Функция для обработки ввода пользователем названия города, чтобы узнать погоду
    """
    city = message.text.strip()
    chat_id = get_chat_id(message)
    response = request_current_weather_data(city_name=city)
    if not response:
        bot.send_message(chat_id=chat_id, text=TEXT_ERROR_REQUEST_WEATHER)
    else:
        current_weather = get_current_weather(response)
        description_weather = get_text_description_weather(current_weather[:-1])
        bot.send_photo(chat_id=chat_id, photo=f"https://openweathermap.org/img/wn/{current_weather[-1]}@4x.png",
                       caption=description_weather, parse_mode="html")
    bot.clear_step_handler_by_chat_id(chat_id=chat_id)


@bot.callback_query_handler(func=lambda call: call.data == CALLBACK_DATA_START_DIALOG_AI)
def start_ai_dialog(call: types.CallbackQuery):
    """
    Функция, которая начинает диалог с ассистентом в чате
    """
    chat_id = get_chat_id_from_call(call)
    message_id = get_message_id_from_call(call)
    bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
    keyboard_end_dialog = get_inline_keyboard(buttons=BUTTON_END_DIALOG_AI)

    # Если сессии для этого чата нет — создаём
    if chat_id not in chat_sessions:
        workflow = get_state_graph()
        workflow.add_edge(START, LLM_MODEL)
        workflow.add_node(LLM_MODEL, call_model)
        memory = create_memory_saver()
        app = workflow.compile(checkpointer=memory)
        # сохраняем в память
        save_session(chat_id, app, memory)
    chat_sessions[chat_id][FLAG_AI_DIALOG_SESSION] = True
    bot.send_message(chat_id, DIALOG_AI_MESSAGE_START_TEXT,
                     reply_markup=keyboard_end_dialog)


def save_session(chat_id, compile_app: langgraph.graph.state.CompiledStateGraph,
                 memory: langgraph.checkpoint.memory.InMemorySaver):
    """
    Устанавливает значения для сохранения памяти в чате
    """
    chat_sessions[chat_id] = {
        APP: compile_app,
        MEMORY: memory
    }


@bot.message_handler(content_types=["text"])
def handle_ai_message(message: types.Message):
    """
    Функция обрабатывающая сообщения в диалоге с ассистентом
    """
    chat_id = get_chat_id(message)
    # используем сохранённую сессию
    session: dict | None = chat_sessions.get(chat_id)
    if not session or not session.get(FLAG_AI_DIALOG_SESSION):
        return
    if message.reply_markup:
        bot.edit_message_reply_markup(chat_id, message_id=message.id, reply_markup=None)
    keyboard_dialog = get_inline_keyboard(buttons={**BUTTON_END_DIALOG_AI, **BUTTON_WEATHER_AGENT})
    user_text = message.text
    app = session[APP]
    input_messages = get_list_input_message(user_text)
    try:
        output = app.invoke({MESSAGES: input_messages},
                            config={"configurable": {"thread_id": chat_id}})
    except Exception:
        keyboard_end_dialog = get_inline_keyboard(buttons=BUTTON_END_DIALOG_AI)
        bot.send_message(chat_id, text=ERROR_REQUEST_AI_TEXT, reply_markup=keyboard_end_dialog)
    else:
        bot.send_message(chat_id, text=output[MESSAGES][-1].content, reply_markup=keyboard_dialog)


@bot.callback_query_handler(func=lambda call: call.data == CALLBACK_DATA_END_DIALOG_AI)
def end_dialog_ai(call: types.CallbackQuery):
    """
    Функция завершающая диалог с ассистентом
    """
    chat_id = get_chat_id_from_call(call)
    message_id = get_message_id_from_call(call)
    bot.edit_message_reply_markup(chat_id, message_id=message_id, reply_markup=None)
    if not checking_ai_dialog(chat_id):
        bot.send_message(chat_id, DIALOG_AI_MESSAGE_END_TEXT)
    if chat_id in chat_sessions:
        chat_sessions[chat_id][FLAG_AI_DIALOG_SESSION] = False


def checking_ai_dialog(chat_id) -> bool:
    """
    Проверка, активен ли в данный момент диалог с ассистентом
    """
    session: dict | None = chat_sessions.get(chat_id)
    return not session or not session.get(FLAG_AI_DIALOG_SESSION)


@bot.callback_query_handler(func=lambda call: call.data == CALLBACK_DATA_WEATHER_AGENT)
def get_weather_agent(call: types.CallbackQuery):
    chat_id = get_chat_id_from_call(call)
    user_text = get_message_text_from_call(call)
    message_id = get_message_id_from_call(call)
    bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
    keyboard_end_dialog = get_inline_keyboard(buttons=BUTTON_END_DIALOG_AI)
    try:
        response = agent_executor.invoke({MESSAGES: [HumanMessage(content=AGENT_HUMAN_MESSAGE + user_text)]})
    except Exception:
        bot.send_message(chat_id, ERROR_REQUEST_AGENT_TEXT, reply_markup=keyboard_end_dialog)
    else:
        bot.send_message(chat_id, response[MESSAGES][-1].content, reply_markup=keyboard_end_dialog)


def get_message_text_from_call(call: types.CallbackQuery) -> str:
    return call.message.text


bot.infinity_polling()
