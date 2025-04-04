import sqlite3
import pandas as pd
import os
from datetime import datetime
import plotly.graph_objects as go


# Convert to absolute path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "assets/macrotracker.db")

def get_db_connection():
    try:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        return conn
    except sqlite3.OperationalError as e:
        print(f"Error opening database: {e}")
        raise

def fetch_data(table: str):
    try:
        with get_db_connection() as conn:
            return pd.read_sql_query(f"SELECT * FROM {table}", conn)
    except Exception as e:
        print(f"Error fetching data from {table}: {e}")
        raise

def update_database(data, table_name: str):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Convert input data to DataFrame
        df_new = pd.DataFrame(data)

        # Fetch existing data from the database
        existing_data = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)

        # Identify rows to delete (based on actual data differences, not just IDs)
        merged_data = existing_data.merge(df_new, on="id", how="left", indicator=True)
        deleted_rows = merged_data[merged_data['_merge'] == 'left_only']

        # Perform deletions if necessary
        for _, row in deleted_rows.iterrows():
            cursor.execute(f"DELETE FROM {table_name} WHERE id = ?", (row['id'],))

        # Perform updates or inserts
        for _, row in df_new.iterrows():
            # Check if the record already exists
            cursor.execute(f"SELECT COUNT(1) FROM {table_name} WHERE id = ?", (row["id"],))
            exists = cursor.fetchone()[0]

            if exists:
                # Update existing record
                columns = ", ".join(f"{k} = ?" for k in row.index if k != "id")
                values = [row[k] for k in row.index if k != "id"]
                values.append(row["id"])
                cursor.execute(f"""
                    UPDATE {table_name}
                    SET {columns}
                    WHERE id = ?
                """, values)
            else:
                # Insert new record
                columns = ", ".join(row.index)
                placeholders = ", ".join(["?" for _ in row.index])
                values = list(row)
                cursor.execute(f"""
                    INSERT INTO {table_name} ({columns})
                    VALUES ({placeholders})
                """, values)

        conn.commit()
    except Exception as e:
        print(f"Error updating {table_name}: {e}")
        raise
    finally:
        conn.close()


def add_new_food(food, weight, fat, carbs, protein):
    conn = get_db_connection()
    cursor = conn.cursor()
    food_data = fetch_data('foods')
    if 'id' in food_data.columns:
        new_id = str(max([int(x) for x in fetch_data('foods')['id']]) + 1)
    else:
        new_id = '1'

    cursor.execute("""
        INSERT INTO foods (id, food, weight, fat, carbs, protein)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (new_id, food, weight, fat, carbs, protein))

    conn.commit()
    conn.close()

def add_new_entry(meal,food, weight):
    conn = get_db_connection()
    cursor = conn.cursor()
    food_data = fetch_data('entries')
    if 'id' in food_data.columns:
        new_id = str(max([int(x) for x in fetch_data('entries')['id']]) + 1)
    else:
        new_id = '1'

    cursor.execute("""
        INSERT INTO entries (id, food, weight, entry_date, meal)
        VALUES (?, ?, ?, ?, ?)
    """, (new_id, food, weight, datetime.now().strftime("%m-%d-%Y"),meal))

    conn.commit()
    conn.close()

def get_foods():
    try:
        with get_db_connection() as conn:
            df = pd.read_sql_query("SELECT food FROM foods", conn)
            return df["food"].unique()
    except Exception as e:
        print(f"Error fetching foods: {e}")
        raise

def remove_all_triggers():
    # Connect to the database
    connection = get_db_connection()
    cursor = connection.cursor()

    # Fetch all trigger names
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'trigger';")
    triggers = cursor.fetchall()

    if triggers:
        # Loop through each trigger and drop it
        for trigger in triggers:
            trigger_name = trigger[0]
            try:
                cursor.execute(f"DROP TRIGGER {trigger_name}")
                print(f"Trigger '{trigger_name}' removed successfully.")
            except sqlite3.Error as e:
                print(f"Failed to remove trigger '{trigger_name}': {e}")
        # Commit changes
        connection.commit()
    else:
        print("No triggers found in the database.")

    # Close the connection
    connection.close()

def list_triggers(table_name):
    # Query triggers for the specified table
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ?;"
    cursor.execute(query, (table_name,))
    triggers = cursor.fetchall()

    # Display the triggers
    if triggers:
        print(f"Triggers for table '{table_name}':")
        for trigger in triggers:
            print(trigger[0])
    else:
        print(f"No triggers found for table '{table_name}'.")

    # Close the connection
    conn.close()

def add_triggers():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TRIGGER total_calories_insert
        AFTER INSERT ON foods
        FOR EACH ROW
        BEGIN
            UPDATE foods
            SET calories = (NEW.fat * 9) + (NEW.carbs * 4) + (NEW.protein * 4)
            WHERE id = NEW.id;
        END;
    ''')
    conn.commit()

    cursor.execute('''
        CREATE TRIGGER total_calories_update
        AFTER UPDATE ON foods
        FOR EACH ROW
        BEGIN
            UPDATE foods
            SET calories = (NEW.fat * 9) + (NEW.carbs * 4) + (NEW.protein * 4)
            WHERE id = NEW.id;
        END;
    ''')
    conn.commit()

def sql(query):
    conn = get_db_connection()
    return pd.read_sql_query(query,conn)


def daily_macros():
    conn = get_db_connection()
    cursor = conn.cursor()
    date = datetime.now().strftime("%m-%d-%Y")
    query = f"""
        SELECT 
        foods.food,
        foods.fat * (entries.weight / foods.weight) AS fat,
        foods.carbs * (entries.weight / foods.weight) AS carb,
        foods.protein * (entries.weight / foods.weight) AS protein,
        ROUND(foods.fat * 9.0 * (entries.weight / foods.weight), 2) + 
        ROUND(foods.carbs * 4.0 * (entries.weight / foods.weight), 2) + 
        ROUND(foods.protein * 4.0 * (entries.weight / foods.weight), 2) as total
        FROM entries
        LEFT JOIN foods
        ON entries.food = foods.food
        WHERE entry_date = '{date}';
    """
    return pd.read_sql_query(query,conn)



def create_gauge_figure():
    target_calories = 2200
    consumed_calories = sum(daily_macros().total)

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=consumed_calories,
        title={"text": "Calories Consumed"},
        gauge={
            'axis': {'range': [0, target_calories]},
            'bar': {'color': "#9678b6"},
            'bgcolor': "#353839",
            'borderwidth': 2,
            'bordercolor': "#000000",
        },
        number={"font": {"color": "#9678b6"}},
    ))
    fig.update_layout( font_color="#9678b6", height=300)
    return fig

def create_macro_figure(consumed, target, label, color):
    consumed_display = min(consumed, target)
    remaining_display = max(target - consumed, 0)  # Prevent negative values

    fig = go.Figure()

    # Add consumed bar (caps at full if over threshold)
    fig.add_trace(go.Bar(
        x=[consumed_display],
        y=[label],
        orientation='h',
        marker_color=color if consumed <= target else "#ff4d4d",  # Red if exceeded
        name='Consumed'
    ))

    # Add remaining bar only if there's remaining space
    if remaining_display > 0:
        fig.add_trace(go.Bar(
            x=[remaining_display],
            y=[label],
            orientation='h',
            marker_color='#8b8589',
            name='Remaining'
        ))

    fig.update_layout(
        barmode='stack',
        plot_bgcolor="#ffffff",
        font_color="#fff",
        height=190,
        xaxis=dict(visible=False),
        yaxis=dict(visible=True, showticklabels=False),
        showlegend=False,  # Hide legend
    )

    return fig
