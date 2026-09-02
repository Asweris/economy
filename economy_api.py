from flask import Flask, jsonify, request
import sqlite3
import os
import json
import requests

app = Flask(__name__)

# Пути к базам
BASE_DIR = os.path.dirname(__file__)
MAIN_DB = os.path.join(BASE_DIR, 'main.db')
LOG_DB = os.path.join(BASE_DIR, 'log.db')

# Токен бота для Discord API (берется из переменной окружения)
BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')

if not BOT_TOKEN:
    print("⚠️ ВНИМАНИЕ: DISCORD_BOT_TOKEN не установлен в переменных окружения!")
    print("⚠️ Поиск по username будет работать некорректно!")

def dict_factory(cursor, row):
    """Превращает row в словарь"""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def get_discord_user(user_id):
    """Получить данные пользователя из Discord API"""
    if not BOT_TOKEN:
        return None
    try:
        response = requests.get(
            f'https://discord.com/api/v10/users/{user_id}',
            headers={'Authorization': f'Bot {BOT_TOKEN}'}
        )
        if response.status_code == 200:
            return response.json()
        return None
    except:
        return None

@app.route('/api/economy/<int:user_id>')
def get_economy(user_id):
    """Возвращает всю экономику пользователя"""
    
    result = {
        'coins': 0,
        'messages': 0,
        'voiceHours': 0,
        'voiceMinutes': 0,
        'reputation': 0,
        'cases': 0,
        'partner': None,
        'marriageTime': 0,
        'marriageBalance': 0,
        'voiceRank': 0,
        'messagesRank': 0,
        'coinsRank': 0
    }

    try:
        # 1. Основные данные из main.db (users)
        conn = sqlite3.connect(MAIN_DB)
        conn.row_factory = dict_factory
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT member_id, money, marry, cases 
            FROM users 
            WHERE member_id = ?
        """, (user_id,))
        user = cursor.fetchone()
        
        if user:
            result['coins'] = user['money'] or 0
            result['cases'] = user['cases'] or 0
            
            # Если есть брак — получаем данные о партнёре
            if user['marry'] and user['marry'] != 0:
                cursor.execute("""
                    SELECT partner_1, partner_2, balance, reg_marry, loveRoom 
                    FROM marrieges 
                    WHERE id = ?
                """, (user['marry'],))
                marriage = cursor.fetchone()
                
                if marriage:
                    # Определяем партнёра (возвращаем ID)
                    if marriage['partner_1'] == user_id:
                        result['partner'] = marriage['partner_2']
                    else:
                        result['partner'] = marriage['partner_1']
                    
                    result['marriageBalance'] = marriage['balance'] or 0
                    result['marriageTime'] = marriage['reg_marry'] or 0
        
        conn.close()
        
        # 2. Голосовой онлайн из voiceactivity_all
        conn = sqlite3.connect(MAIN_DB)
        conn.row_factory = dict_factory
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT total_hours, total_minutes 
            FROM voiceactivity_all 
            WHERE member_id = ?
        """, (user_id,))
        voice = cursor.fetchone()
        
        if voice:
            result['voiceHours'] = voice['total_hours'] or 0
            result['voiceMinutes'] = voice['total_minutes'] or 0
        else:
            # Если пользователя нет в voiceactivity_all — создаём запись
            cursor.execute("""
                INSERT INTO voiceactivity_all (member_id, joined_at, left_at, total_hours, total_minutes) 
                VALUES (?, 0, 0, 0, 0)
            """, (user_id,))
            conn.commit()
        
        conn.close()
        
        # 3. Сообщения из log.db
        conn = sqlite3.connect(LOG_DB)
        conn.row_factory = dict_factory
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT count 
            FROM messages 
            WHERE member_id = ?
        """, (user_id,))
        msg = cursor.fetchone()
        
        if msg:
            result['messages'] = msg['count'] or 0
        else:
            # Если нет записи — создаём
            cursor.execute("""
                INSERT INTO messages (member_id, count) 
                VALUES (?, 0)
            """, (user_id,))
            conn.commit()
        
        conn.close()
        
        # ============================================================
        # 4. РЕПУТАЦИЯ из user_profile
        # ============================================================
        try:
            conn = sqlite3.connect(MAIN_DB)
            cursor = conn.cursor()
            
            # Проверяем существование таблицы user_profile
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='user_profile'
            """)
            table_exists = cursor.fetchone()
            
            if table_exists:
                cursor.execute("""
                    SELECT reputation 
                    FROM user_profile 
                    WHERE user_id = ?
                """, (user_id,))
                rep = cursor.fetchone()
                
                if rep:
                    result['reputation'] = rep[0] or 0
                else:
                    # Создаём запись если нет
                    cursor.execute("""
                        INSERT INTO user_profile (user_id, reputation, status, xp, level) 
                        VALUES (?, 0, '', 0, 0)
                    """, (user_id,))
                    conn.commit()
                    result['reputation'] = 0
            else:
                # Если таблицы нет - создаём
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_profile (
                        user_id INTEGER PRIMARY KEY,
                        reputation INTEGER DEFAULT 0,
                        status TEXT DEFAULT '',
                        xp INTEGER DEFAULT 0,
                        level INTEGER DEFAULT 0
                    )
                """)
                cursor.execute("""
                    INSERT INTO user_profile (user_id, reputation, status, xp, level) 
                    VALUES (?, 0, '', 0, 0)
                """, (user_id,))
                conn.commit()
                result['reputation'] = 0
            
            conn.close()
        except Exception as e:
            print(f"⚠️ Ошибка получения репутации: {e}")
            result['reputation'] = 0
        
        # 5. Места в топах (ранги)
        # Ранг по голосовому онлайну
        conn = sqlite3.connect(MAIN_DB)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) + 1 
            FROM voiceactivity_all 
            WHERE total_hours > (SELECT COALESCE(total_hours, 0) FROM voiceactivity_all WHERE member_id = ?)
               OR (total_hours = (SELECT COALESCE(total_hours, 0) FROM voiceactivity_all WHERE member_id = ?) 
                   AND total_minutes > (SELECT COALESCE(total_minutes, 0) FROM voiceactivity_all WHERE member_id = ?))
        """, (user_id, user_id, user_id))
        rank = cursor.fetchone()
        if rank and rank[0] is not None:
            result['voiceRank'] = rank[0]
        else:
            result['voiceRank'] = 0
        
        conn.close()
        
        # Ранг по сообщениям
        conn = sqlite3.connect(LOG_DB)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) + 1 
            FROM messages 
            WHERE count > (SELECT COALESCE(count, 0) FROM messages WHERE member_id = ?)
        """, (user_id,))
        rank = cursor.fetchone()
        if rank and rank[0] is not None:
            result['messagesRank'] = rank[0]
        else:
            result['messagesRank'] = 0
        
        conn.close()
        
        # Ранг по монетам
        conn = sqlite3.connect(MAIN_DB)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) + 1 
            FROM users 
            WHERE money > (SELECT COALESCE(money, 0) FROM users WHERE member_id = ?)
        """, (user_id,))
        rank = cursor.fetchone()
        if rank and rank[0] is not None:
            result['coinsRank'] = rank[0]
        else:
            result['coinsRank'] = 0
        
        conn.close()
        
        print(f"✅ Данные для {user_id}: репутация={result['reputation']}, партнер={result['partner']}")
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return jsonify({
            'error': str(e),
            'coins': 0,
            'messages': 0,
            'voiceHours': 0,
            'voiceMinutes': 0,
            'reputation': 0,
            'cases': 0,
            'partner': None,
            'marriageTime': 0,
            'marriageBalance': 0,
            'voiceRank': 0,
            'messagesRank': 0,
            'coinsRank': 0
        })

@app.route('/api/economy/top/voice')
def get_top_voice():
    """Топ по голосовому онлайну"""
    conn = sqlite3.connect(MAIN_DB)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT member_id, total_hours, total_minutes 
        FROM voiceactivity_all 
        ORDER BY total_hours DESC, total_minutes DESC 
        LIMIT 30
    """)
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        result.append({
            'user_id': row[0],
            'hours': row[1] or 0,
            'minutes': row[2] or 0
        })
    return jsonify(result)

@app.route('/api/economy/top/coins')
def get_top_coins():
    """Топ по монетам"""
    conn = sqlite3.connect(MAIN_DB)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT member_id, money 
        FROM users 
        ORDER BY money DESC 
        LIMIT 30
    """)
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        result.append({
            'user_id': row[0],
            'coins': row[1] or 0
        })
    return jsonify(result)

@app.route('/api/economy/top/messages')
def get_top_messages():
    """Топ по сообщениям"""
    conn = sqlite3.connect(LOG_DB)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT member_id, count 
        FROM messages 
        ORDER BY count DESC 
        LIMIT 30
    """)
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        result.append({
            'user_id': row[0],
            'messages': row[1] or 0
        })
    return jsonify(result)

# ============================================================
# НОВЫЙ ЭНДПОИНТ: ПОЛУЧЕНИЕ ВСЕХ ПОЛЬЗОВАТЕЛЕЙ
# ============================================================
@app.route('/api/users/all')
def get_all_users():
    """Получить всех пользователей из базы"""
    try:
        conn = sqlite3.connect(MAIN_DB)
        cursor = conn.cursor()
        cursor.execute("SELECT member_id FROM users")
        users = cursor.fetchall()
        conn.close()
        
        result = []
        for (member_id,) in users:
            result.append({'member_id': member_id})
        return jsonify(result)
    except Exception as e:
        print(f"❌ Ошибка получения пользователей: {e}")
        return jsonify({'error': str(e)}), 500

# ============================================================
# НОВЫЙ ЭНДПОИНТ: ПОИСК ПОЛЬЗОВАТЕЛЯ ПО USERNAME
# ============================================================
@app.route('/api/search/user', methods=['GET'])
def search_user():
    """Поиск пользователя по username или ID"""
    query = request.args.get('q', '').strip()
    
    if not query:
        return jsonify({'error': 'Пустой запрос'}), 400
    
    print(f"🔍 Поиск пользователя: {query}")
    
    try:
        conn = sqlite3.connect(MAIN_DB)
        cursor = conn.cursor()
        
        # Пробуем найти по ID (если запрос - число)
        if query.isdigit():
            cursor.execute("SELECT member_id FROM users WHERE member_id = ?", (int(query),))
            result = cursor.fetchone()
            if result:
                conn.close()
                print(f"✅ Найден по ID: {result[0]}")
                return jsonify({'user_id': result[0]})
        
        # Ищем по username через Discord API
        search_name = query.lower()
        if search_name.startswith('@'):
            search_name = search_name[1:]
        
        # Получаем всех пользователей из базы
        cursor.execute("SELECT member_id FROM users")
        all_users = cursor.fetchall()
        conn.close()
        
        print(f"📊 Всего пользователей в базе: {len(all_users)}")
        
        for (user_id,) in all_users:
            try:
                discord_user = get_discord_user(user_id)
                if discord_user:
                    username = (discord_user.get('username', '') or '').lower()
                    global_name = (discord_user.get('global_name', '') or '').lower()
                    
                    # Проверяем точное совпадение или частичное
                    if search_name == username or search_name == global_name:
                        print(f"✅ Найден по точному совпадению: {user_id} ({username})")
                        return jsonify({'user_id': user_id})
                    
                    if search_name in username or search_name in global_name:
                        print(f"✅ Найден по частичному совпадению: {user_id} ({username})")
                        return jsonify({'user_id': user_id})
            except Exception as e:
                continue
        
        print(f"❌ Пользователь не найден: {query}")
        return jsonify({'error': 'Пользователь не найден'}), 404
        
    except Exception as e:
        print(f"❌ Ошибка поиска: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3001, debug=False)
