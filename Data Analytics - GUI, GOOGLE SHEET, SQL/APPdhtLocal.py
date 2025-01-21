# -*- coding: utf-8 -*-
# Author: Noorul Ghousiah Binti Noordeen Sahib (https://github.com/noorulghousiah)
# this is code for dht11 sensor GUI APP. The app includes sensor reading, send data to local database and to google sheets, and realtime data analytics.

#import for design
import sys
import tkinter as tk
import tkinter.ttk as ttk
from tkinter.constants import *
import os.path
from PIL import Image, ImageTk
from tkinter import messagebox

#import libraries for basic user interface and data handling
import requests
import json
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import sqlite3

#import for DHT11
import RPi.GPIO as GPIO
import dht11
import time

#import to connect to google sheets
from google.oauth2 import service_account
from googleapiclient.discovery import build
import numpy as np

# Initialize GPIO to read at pin 4
GPIO.setwarnings(True)
GPIO.setmode(GPIO.BCM)
instance = dht11.DHT11(pin=4)
    
#----------------------------------------------------------------------------
# Google Sheets setup: functions to manage data in google sheets
#----------------------------------------------------------------------------

# Create a service object for interacting with Google Sheets API
def get_service():
    # Load credentials from the service account file
    creds = service_account.Credentials.from_service_account_file(
        "mydata.json", # Path to your service account credentials file
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )

    # Build the Sheets API service object using the credentials
    service = build('sheets', 'v4', credentials=creds)
    return service


# Function to create a new sheet in the spreadsheet if it doesn't already exist
def create_sheet_if_not_exists(service, spreadsheet_id, sheet_name):
    try:
        # Get metadata of the spreadsheet to check for existing sheets
        sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = sheet_metadata.get('sheets', [])
        sheet_names = [sheet['properties']['title'] for sheet in sheets]

        # If the specified sheet name does not exist, create it
        if sheet_name not in sheet_names:
            requests = [{
                "addSheet": {
                    "properties": {
                        "title": sheet_name
                    }
                }
            }]
            body = {
                'requests': requests
            }

            # Send the batchUpdate request to create the sheet
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body
            ).execute()
            print(f"Sheet '{sheet_name}' created.")
        else:
            print(f"Sheet '{sheet_name}' already exists.")
    except Exception as e:
        print(f"Failed to create sheet: {str(e)}")


# Function to ensure that the specified sheet has the correct header row
def ensure_sheet_header(service, spreadsheet_id, sheet_name, header):
    try:
        # Retrieve the first row (header) from the specified sheet
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A1:Z1"
        ).execute()
        values = result.get('values', [])

        # If the header row is empty, update it with the provided header
        if not values:  
            body = {"values": [header]} # The header to insert
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{sheet_name}!A1:Z1",
                valueInputOption="USER_ENTERED",  # Insert the values as entered by the user
                body=body
            ).execute()
            print(f"Header created in '{sheet_name}' sheet.")
        else:
            print(f"Header already exists in '{sheet_name}' sheet.")
    except Exception as e:
        print(f"Failed to ensure header in '{sheet_name}' sheet: {str(e)}")


# Function to log data to a Google Sheets sheet
def log_to_gsheet(service, spreadsheet_id, sheet_name, values):
    try:
        # Prepare the data to be appended to the sheet
        body = {
            "values": [values]
        }
        
        # Append the data to the next available row in column A
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A:A",  # Append data to the next available row in column A
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()
        print(f"Data logged to sheet: {sheet_name}")
    except Exception as e:
        if "RATE_LIMIT_EXCEEDED" in str(e):
            print("Rate limit exceeded. Retrying after a short delay...")
            time.sleep(10)  # Wait for 10 seconds before retrying
            log_to_gsheet(service, spreadsheet_id, sheet_name, values) # Retry logging data
        else:
            print(f"Failed to log data: {str(e)}")


# Function to retrieve data from a Google Sheets sheet
def get_data_from_sheet(service, spreadsheet_id, sheet_name):
    try:
        # Retrieve all data from the specified sheet
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}"
        ).execute()
        return result.get('values', [])
    except Exception as e:
        print(f"Failed to get data from sheet: {str(e)}")
        return []


# Function to clear all data from a Google Sheets sheet
def clear_sheet(service, spreadsheet_id, sheet_name):
    try:
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A1:Z1000",
            body={}
        ).execute()
        print(f"Data cleared from sheet: {sheet_name}")
    except Exception as e:
        if "RATE_LIMIT_EXCEEDED" in str(e):
            print("Rate limit exceeded. Retrying after a short delay...")
            time.sleep(10)  # Wait for 10 seconds before retrying
            clear_sheet(service, spreadsheet_id, sheet_name)
        else:
            print(f"Failed to clear data from sheet: {str(e)}")


# Function to summarize data from a Google Sheets sheet
def summarize_data(data):
    numeric_data = []

    # Process each row of data, converting valid numerical values and ignoring invalid ones
    for row in data:
        numeric_row = []
        for cell in row[1:]:  # Skip the timestamp
            try:
                numeric_row.append(float(cell)) # Convert cell data to float
            except ValueError:
                continue # Skip non-numeric values
        if numeric_row:
            numeric_data.append(numeric_row)

    # Convert the collected numerical data to a NumPy array for easier processing
    numeric_array = np.array(numeric_data, dtype=float) if numeric_data else np.array([])

    # If the array is empty, return an empty list
    if numeric_array.size == 0:
        return []

    # Calculate mean, minimum, and maximum values for each column
    mean_values = np.mean(numeric_array, axis=0).tolist()
    min_values = np.min(numeric_array, axis=0).tolist()
    max_values = np.max(numeric_array, axis=0).tolist()
    
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    return [timestamp] + mean_values + min_values + max_values # Return the summary data


# Function to trim the 'RawHistory' sheet if it exceeds a certain number of rows
def check_and_trim_rawhistory(service, spreadsheet_id, sheet_name, max_rows=200):
    try:
        # Get sheet metadata
        sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = sheet_metadata.get('sheets', [])
        sheet_id = None

        # Find the sheet ID for the specified sheet name
        for sheet in sheets:
            if sheet['properties']['title'] == sheet_name:
                sheet_id = sheet['properties']['sheetId']
                break

        if sheet_id is None:
            print(f"Sheet ID for '{sheet_name}' not found.")
            return

        # Retrieve all rows from the sheet
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}"
        ).execute()
        rows = result.get('values', [])

        # If the number of rows exceeds the maximum, trim the sheet
        if len(rows) > max_rows:
            # Calculate how many rows to delete
            rows_to_delete = len(rows) - max_rows + 20
            print(f"Trimming {rows_to_delete} rows from {sheet_name} sheet")

            # Create a batch request to delete rows from the top (excluding the header row)
            batch_request = [{
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": 1,  # Skip the header row
                        "endIndex": 1 + rows_to_delete # Specify the range of rows to delete
                    }
                }
            }]

            # Send the batchUpdate request to delete the rows
            body = {'requests': batch_request}
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body
            ).execute()
            print(f"Trimmed {rows_to_delete} rows from {sheet_name} sheet")
    except Exception as e:
        print(f"Failed to trim data from {sheet_name}: {str(e)}")

#----------------------------------------------------------------------------------




# This class defines the base design and layout common to all pages in the application
class BaseToplevel:
		
    # Define common configuration dictionary
    common_config = {
        'activebackground': "#d9d9d9",
        'activeforeground': "black",
        
        'compound': 'left',
        'disabledforeground': "#b4b4b4",
        'font': "-family {Segoe UI} -size 9",
        'foreground': "Black",
        'highlightcolor': "Black"
    }

    common_configbutton = {
        'activebackground': "#d9d9d9",
        'activeforeground': "black",
        'compound': 'left',
        'disabledforeground': "#b4b4b4",
        'font': "-family {Segoe UI} -size 9",
        'foreground': "Black",
        'highlightcolor': "Black"
    }

    def __init__(self, top):
        #Initialize the main window
        self.top = top
        
        #self.original_image = original_image
        self.original_image = Image.open(os.path.join(os.path.dirname(__file__), 'asd.jpg')) 

        
        top.geometry("812x574+340+107")# Set window size and position
        top.minsize(120, 1) # Set minimum size for the window
        top.maxsize(1370, 749)  # Set maximum size for the window
        top.resizable(1,  1) # Allow window resizing
        top.title("DHT11") # Set the window title
        top.configure(background="#99b4d1") # Set background color
        top.configure(highlightcolor="Black") # Set highlight color

        #33333333-----HEADER OF PAGE----------3333333333333333333333333333
        #Header Text
        self.Label1 = tk.Label(self.top)
        self.Label1.place(relx=0.21, rely=0.0, relheight=0.183, relwidth=1.0)
        self.Label1.configure(activebackground="#d9d9d9")
        self.Label1.configure(activeforeground="black")
        self.Label1.configure(anchor='w')
        self.Label1.configure(background="#090033")
        self.Label1.configure(compound='right')
        self.Label1.configure(disabledforeground="#b4b4b4")
        self.Label1.configure(font="-family {Segoe UI} -size 13 -weight bold")
        self.Label1.configure(foreground="#ffffff")
        self.Label1.configure(highlightcolor="Black")
        self.Label1.configure(justify='left')
        self.Label1.configure(padx="70")
        self.Label1.configure(text='''DHT11 Temperature and Humidity\nMonitoring System''')

        # Create frames for the header section to display an image (logo) 
        self.TFrame1 = tk.Frame(self.top)
        self.TFrame1.place(relx=0.0, rely=0.0, relheight=0.183, relwidth=0.21)       
        self.TFrame1.configure(relief='flat')
        self.TFrame1.configure(borderwidth="2")
        self.TFrame1.configure(highlightcolor="Black")
        self.TFrame1.configure(background="#090033")

        self.Frame1 = tk.Frame(self.top)
        self.Frame1.place(relx=0.79, rely=0.0, relheight=0.183, relwidth=0.21)
        self.Frame1.configure(relief='flat')
        self.Frame1.configure(borderwidth="2")
        self.Frame1.configure(highlightcolor="Black")
        self.Frame1.configure(background="#090033")
        
        # Add the image to TFrame1 and Frame 1
        self.original_image = Image.open(os.path.join(os.path.dirname(__file__), 'asd.jpg')) 
        self.logo_photo = ImageTk.PhotoImage(self.original_image)
       
        self.label_logo_1 = tk.Label(self.TFrame1, image=self.logo_photo)
        self.label_logo_1.image = self.logo_photo  # Keep a reference to the image
        self.label_logo_1.pack(expand=True)
        
        self.label_logo_2 = tk.Label(self.Frame1, image=self.logo_photo)
        self.label_logo_2.image = self.logo_photo  # Keep a reference to the image
        self.label_logo_2.pack(expand=True)
        # Bind the frame's configure event to resize the image dynamically with window resizing
        self.Frame1.bind("<Configure>", self.resize_image)

        #---------------------------------------------------------------------- 
        
    def resize_image(self, event):
        # Resize the image to fit the Frame1 dimensions
        frame_width = self.Frame1.winfo_width()
        frame_height = self.Frame1.winfo_height()
        
        if frame_width > 0 and frame_height > 0:  # Ensure the frame has been rendered
            resized_image = self.original_image.resize((frame_width, frame_height), Image.LANCZOS)
            self.logo_photo = ImageTk.PhotoImage(resized_image)

            self.label_logo_1.configure(image=self.logo_photo)
            self.label_logo_1.image = self.logo_photo  # Keep a reference to the image
            
            self.label_logo_2.configure(image=self.logo_photo)
            self.label_logo_2.image = self.logo_photo  # Keep a reference to the image

# This class defines additional GUI elements for the main application window (page1)
class Toplevel1(BaseToplevel):
    def __init__(self, top=None):
        super().__init__(top)
        self.top = top
        top.title("DHT11")

        #####FRAME to display statistics---------------------------
        self.Frame3 = tk.Frame(self.top)
        self.Frame3.place(relx=0.025, rely=0.767, relheight=0.183, relwidth=0.606)
        self.Frame3.configure(relief='groove')
        self.Frame3.configure(borderwidth="2")
        self.Frame3.configure(relief="groove")
        self.Frame3.configure(highlightcolor="Black")

        #current data value
        self.Label4 = tk.Label(self.Frame3)
        self.Label4.place(relx=0.02, rely=0.381, height=21, width=76)
        self.Label4.configure(**self.common_config)
        self.Label4.configure(anchor='w')
        self.Label4.configure(text='''Humidity''')

        self.Label2 = tk.Label(self.Frame3)
        self.Label2.place(relx=0.02, rely=0.095, height=21, width=76)
        self.Label2.configure(**self.common_config)
        self.Label4.configure(anchor='w')
        self.Label2.configure(text='''Temperature''')

        self.entry_temperature = tk.Label(self.Frame3)
        self.entry_temperature.place(relx=0.224, rely=0.095, height=21, width=60)
        self.entry_temperature.configure(**self.common_config)
        self.entry_temperature.configure(text='''= N/A''')

        self.entry_humidity = tk.Label(self.Frame3)
        self.entry_humidity.place(relx=0.224, rely=0.381, height=21, width=60)
        self.entry_humidity.configure(**self.common_config)
        self.entry_humidity.configure(text='''= N/A''')


        #Max and Min recorded data values
        self.Label9 = tk.Label(self.Frame3)
        self.Label9.place(relx=0.407, rely=0.095, height=21, width=114)
        self.Label9.configure(**self.common_config)
        self.Label9.configure(anchor='w')
        self.Label9.configure(text='''Max''')

        self.Label7 = tk.Label(self.Frame3)
        self.Label7.place(relx=0.407, rely=0.381, height=21, width=32)
        self.Label7.configure(**self.common_config)
        self.Label7.configure(anchor='w')
        self.Label7.configure(text='''Max''')

        self.Label5 = tk.Label(self.Frame3)
        self.Label5.place(relx=0.711, rely=0.095, height=21, width=27)
        self.Label5.configure(**self.common_config)
        self.Label5.configure(anchor='w')
        self.Label5.configure(text='''Min''')

        self.Label12 = tk.Label(self.Frame3)
        self.Label12.place(relx=0.711, rely=0.381, height=21, width=27)
        self.Label12.configure(**self.common_config)
        self.Label12.configure(anchor='w')
        self.Label12.configure(text='''Min''')

        self.label_max_temperature = tk.Label(self.Frame3)
        self.label_max_temperature.place(relx=0.488, rely=0.095, height=21, width=48)
        self.label_max_temperature.configure(**self.common_config)
        self.label_max_temperature.configure(text='''= N/A''')

        self.label_max_humidity = tk.Label(self.Frame3)
        self.label_max_humidity.place(relx=0.488, rely=0.381, height=21, width=48)
        self.label_max_humidity.configure(**self.common_config)
        self.label_max_humidity.configure(text='''= N/A''')

        self.label_min_temperature = tk.Label(self.Frame3)
        self.label_min_temperature.place(relx=0.793, rely=0.095, height=21, width=48)
        self.label_min_temperature.configure(**self.common_config)
        self.label_min_temperature.configure(text='''= N/A''')

        self.label_min_humidity = tk.Label(self.Frame3)
        self.label_min_humidity.place(relx=0.793, rely=0.381, height=21, width=48)
        self.label_min_humidity.configure(**self.common_config)
        self.label_min_humidity.configure(text='''= N/A''')

        #display time of last updated data
        self.label_last_updatedr = ttk.Label(self.top, text="Last Updated: Not available")
        self.label_last_updatedr.pack(side=tk.BOTTOM, anchor=tk.E)

        #display any warning messages
        self.label_warnings = tk.Label(self.Frame3)
        self.label_warnings.place(relx=0.407, rely=0.762, height=21, width=284)
        self.label_warnings.configure(**self.common_config)
        self.label_warnings.configure(font="-family {Segoe UI Black} -size 8 -weight bold")
        self.label_warnings.configure(foreground="#ff0000")
        self.label_warnings.configure(text='''''')

        #----additional designs
        self.TSeparator1 = ttk.Separator(self.Frame3)
        self.TSeparator1.place(relx=0.386, rely=0.0,  relheight=2.286)
        self.TSeparator1.configure(orient="vertical")
        
        self.TSeparator2 = ttk.Separator(self.Frame3)
        self.TSeparator2.place(relx=0.004, rely=0.305,  relwidth=0.996)

        self.TSeparator3 = ttk.Separator(self.Frame3)
        self.TSeparator3.place(relx=0.004, rely=0.59,  relwidth=0.996)

        self.labelp = tk.Label(self.Frame3)
        self.labelp.place(relx=0.02, rely=0.7, height=21, width=120)
        self.labelp.configure(**self.common_config)
        self.labelp.configure(font="-family {Segoe UI} -size 8 -weight bold")
        self.labelp.configure(text='''Current Live Data''')

        #-------------------------------------------------------------

        #####FRAME to put user control buttons
        self.Frame2 = tk.Frame(self.top)
        self.Frame2.place(relx=0.64, rely=0.261, relheight=0.688, relwidth=0.339)
        self.Frame2.configure(background="#4d5a69")
        self.Frame2.configure(borderwidth="2")
        self.Frame2.configure(relief="flat")
        self.Frame2.configure(highlightcolor="Black")

        #start reading sensor data
        self.Button1 = tk.Button(self.Frame2)
        self.Button1.place(relx=0.327, rely=0.177, height=26, width=107)
        self.Button1.configure(**self.common_configbutton)
        self.Button1.configure(text='''Start Program''')
        self.Button1.configure(command=self.start_fetching)

        #stop reading sensor data
        self.Button2 = tk.Button(self.Frame2)
        self.Button2.place(relx=0.327, rely=0.304, height=26, width=107)
        self.Button2.configure(**self.common_configbutton)
        self.Button2.configure(text='''Stop Program''')
        self.Button2.configure(command=self.stop_fetching)

        #reset any warning messages displayed
        self.Button3 = tk.Button(self.Frame2)
        self.Button3.place(relx=0.109, rely=0.911, height=26, width=107)
        self.Button3.configure(**self.common_configbutton)
        self.Button3.configure(text='''Reset Warning''')
        self.Button3.configure(command=self.refresh_warnings)

        #open history page (2nd page)
        self.Button4 = tk.Button(self.Frame2)
        self.Button4.place(relx=0.327, rely=0.43, height=26, width=107)
        self.Button4.configure(**self.common_configbutton)
        self.Button4.configure(text='''History''')
        self.Button4.configure(command=self.open_history_page)

        #####LIVE GRAPH########################--------------------------
        self.Framegraph = tk.Frame(self.top)
        self.Framegraph.place(relx=0.025, rely=0.261, relheight=0.484, relwidth=0.606)

        self.figure, self.ax = plt.subplots(2, 1, figsize=(8, 6))
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.Framegraph)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        #####INITIALIZATION OF PROGRAM#############------------------------------
        # Initialize the data lists and fetching control
        self.temperature_data = []
        self.humidity_data = []
        self.fetching_data = False

        # Connect to SQLite database
        self.conn = sqlite3.connect('sensors.db')
        self.cursor = self.conn.cursor()

        # Create tables if they don't exist
        self.create_tables()

        # Schedule daily summary task
        # choose between schedule daily summary or schedule minute summary.
        #if choose daily summary, change the next line to "self.schedule_daily_summary():
        self.schedule_minute_summary()

    def open_history_page(self):
        # Create a new top-level window for the history page
        self.history_window = tk.Toplevel(self.top)

        # Initialize the history page within the new window
        self.history_page = Toplevel2(top=self.history_window)

        # Make the new window a child of the main window
        self.history_window.transient(self.top)

        # Make the new window modal (i.e., block interaction with the main window)
        self.history_window.grab_set() 

    def create_tables(self):
        # Create the necessary SQlite database tables if it doesn't exist
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS monitoring (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL,
            temperature REAL NOT NULL,
            humidity REAL NOT NULL
        )
        ''')
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            mean_temperature REAL,
            max_temperature REAL,
            min_temperature REAL,
            mean_humidity REAL,
            max_humidity REAL,
            min_humidity REAL
        )
        ''')

        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS RawHistory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL,
            temperature REAL NOT NULL,
            humidity REAL NOT NULL
        )
        ''')

        # Commit the tables creation to the database
        self.conn.commit()

    def schedule_daily_summary(self):
        # Get the current date and time
        now = datetime.now()

        # Set the next run time to 23:30:00 on the current day
        next_run = now.replace(hour=23, minute=30, second=0, microsecond=0)

        # If the current time is past the next run time, schedule for the next day
        if now > next_run:
            next_run += timedelta(days=1)

        # Calculate the wait time in seconds
        wait_time = (next_run - now).total_seconds()

        # Schedule the daily summary task
        self.top.after(int(wait_time * 1000), self.daily_summary)
        
    def schedule_minute_summary(self):
        now = datetime.now()

        # Schedule the next summary to run in 2 minutes
        next_run  = now + timedelta(minutes=2)
        if now > next_run:
            next_run += timedelta(minutes=2)
        wait_time = (next_run - now).total_seconds()

        # Schedule the minute summary task
        self.top.after(int(wait_time * 1000), self.minute_summary)
        

    #******************************READ THIS FOR SCHEDULING***********
    #current code use minute summary 2min, if want to use daily summary,
    #just change the function name from def minute_summary(self): to
    #def daily_summary(self):
    def minute_summary(self):
        # Get the current date for history record
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Calculate daily statistics
        self.cursor.execute('''
        SELECT AVG(temperature), MAX(temperature), MIN(temperature),
               AVG(humidity), MAX(humidity), MIN(humidity)
        FROM monitoring
        ''')
        stats = self.cursor.fetchone()
        
        # Check if stats are valid (not empty)
        if stats and stats[0] is not None:
            history_data =(current_date, *stats)

            # Insert into local database
            self.cursor.execute('''
            INSERT INTO history (date, mean_temperature, max_temperature, min_temperature, mean_humidity, max_humidity, min_humidity)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', history_data)
            self.conn.commit()
            
            log_to_gsheet(service, spreadsheet_id, "History", history_data)
        

        self.cursor.execute('DELETE FROM monitoring')
        self.conn.commit()
            
        # Clear Monitoring sheet
        clear_sheet(service, spreadsheet_id, "Monitoring")

        # Reschedule the daily summary task
        self.schedule_minute_summary();

    def start_fetching(self):
        global start_time
        start_time = datetime.now()

        # Start fetching data if it's not already being fetched
        if not self.fetching_data:
            self.fetching_data = True
            self.load_sensor_data()

    def stop_fetching(self):
        self.fetching_data = False

    def load_sensor_data(self):
    # If fetching data is stopped, exit the function
        if not self.fetching_data:
            return

        try:
            result = instance.read()
            if result.is_valid():
                    temperature = result.temperature
                    humidity = result.humidity
            
                    # Update the temperature and humidity display in the GUI
                    self.entry_temperature.config(text= f"{temperature} C")
                    self.entry_humidity.config(text= f"{humidity} %")

                    # Append the temperature and humidity data for plotting
                    now = datetime.now()
                    self.temperature_data.append((now, temperature))
                    self.humidity_data.append((now, humidity))

                    # Insert data into the SQLite Local database
                    self.cursor.execute('''
                    INSERT INTO monitoring (time, temperature, humidity) VALUES (?, ?, ?)
                    ''', (now.strftime("%Y-%m-%d %H:%M:%S"), temperature, humidity))
                    self.conn.commit()

                    self.cursor.execute('''
                    INSERT INTO RawHistory (time, temperature, humidity) VALUES (?, ?, ?)
                    ''', (now.strftime("%Y-%m-%d %H:%M:%S"), temperature, humidity))
                    self.conn.commit()
                    
                    # Log data to Google Sheets
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    log_to_gsheet(service, spreadsheet_id, "RawHistory", [timestamp, temperature, humidity])
                    log_to_gsheet(service, spreadsheet_id, "Monitoring", [timestamp, temperature, humidity])
                        
                    # Check and trim RawHistory if it exceeds the threshold
                    check_and_trim_rawhistory(service, spreadsheet_id, "RawHistory", max_rows=1000)

                    # Update the last updated label
                    self.label_last_updatedr.config(text=f"Last Updated: {now.strftime('%Y-%m-%d %H:%M:%S')}")

                    # Check for alerts
                    self.check_for_alerts(temperature, humidity)

                    # Calculate and display statistics
                    self.display_statistics()

                    # Clear previous data from the plots
                    self.ax[0].cla()
                    self.ax[1].cla()

                    # Extract time and data for plotting
                    times, temps = zip(*self.temperature_data) if self.temperature_data else ([], [])
                    _, hums = zip(*self.humidity_data) if self.humidity_data else ([], [])

                    # Plot the temperature and humidity data
                    self.ax[0].plot(times, temps, '-', color='tab:red', label='Temperature')
                    self.ax[1].plot(times, hums, '-', color='tab:blue', label='Humidity')

                    # Set axis labels
                    self.ax[0].set_ylabel("Temperature (C)")
                    self.ax[1].set_ylabel("Humidity (%)")
                    #self.ax[1].set_xlabel("Time")

                    # Set date format for x-axis
                    for axis in self.ax:
                        axis.xaxis.set_major_formatter(DateFormatter('%H:%M'))

                        # Set locator to show only the start and end ticks
                        if times:
                            current_time = datetime.now()
                            if current_time - start_time >= timedelta(minutes=2):
                                if current_time - start_time >= timedelta(minutes=10):
                                    # Show ticks for 10 minutes ago and the current time
                                    ten_minutes_ago = times[-1] - timedelta(minutes=9)
                                    first_tick = min(times, key=lambda x: abs(x - ten_minutes_ago))
                                    axis.set_xticks([first_tick, times[-1]])
                                else:
                                    # Show ticks for the first and last time points
                                    axis.set_xticks([times[0], times[-1]])
                                     
                            else:
                                #print("Less than 2 minutes have passed")
                                axis.set_xticks([times[0]])
                        else:
                            axis.set_xticks([])

                        axis.legend()
                        axis.grid(True)

                    # Adjust x-axis limits to show the last 10 minutes of data
                    if times:
                        max_time = max(times)
                        min_time = max_time - timedelta(minutes=10)
                        self.ax[0].set_xlim(min_time, max_time)
                        self.ax[1].set_xlim(min_time, max_time)

                    # Draw the updated plots
                    self.canvas.draw()

                    # Repeat every 2 seconds if fetching is active
                    if self.fetching_data:
                        self.top.after(2000, self.load_sensor_data)
            else:
                    print("Error: %d" % result.error_code)
                    self.top.after(1000, self.load_sensor_data)
        except Exception as ex:
            print(f"Error: {ex}")
            self.top.after(1000, self.load_sensor_data)
            
    def display_statistics(self):
        # Display max and min temperature and humidity if data is available
        if self.temperature_data:
            temperatures = [temp for _, temp in self.temperature_data]
            humidity = [hum for _, hum in self.humidity_data]
            self.label_max_temperature.config(text=f"{max(temperatures):.2f} C")
            self.label_min_temperature.config(text=f"{min(temperatures):.2f} C")
            self.label_max_humidity.config(text=f"{max(humidity):.2f} %")
            self.label_min_humidity.config(text=f"{min(humidity):.2f} %")

           
            

    def check_for_alerts(self, max_temp, max_hum):
        # Check if temperature or humidity exceeds threshold
        alert_message = ""
        if max_temp > 30:
            alert_message += f"Alert: Temperature exceeded 30 C!\n"
        if max_hum > 70:
            alert_message += f"Alert: Humidity exceeded 70 %!\n"

        if alert_message:
            self.label_warnings.config(text=alert_message)
        else:
            pass
        
    def refresh_warnings(self):
        # Clear the warnings display
        self.label_warnings.config(text="")  # Clear warnings

#This is for the second page of the APP - Show History table from local database
class Toplevel2(BaseToplevel):
    def __init__(self, top=None):
        super().__init__(top)
        self.top = top
        top.title("Toplevel 1")

        #title for the data history section
        self.Label16 = tk.Label(self.top)
        self.Label16.place(relx=0.024, rely=0.205, height=21, width=204)
        self.Label16.configure(activebackground="#99b4d1")
        self.Label16.configure(activeforeground="black")
        self.Label16.configure(anchor='w')
        self.Label16.configure(background="#99b4d1")
        self.Label16.configure(compound='left')
        self.Label16.configure(disabledforeground="#b4b4b4")
        self.Label16.configure(font="-family {Lucida Console} -size 14 -weight bold -underline 1")
        self.Label16.configure(foreground="Black")
        self.Label16.configure(highlightcolor="Black")
        self.Label16.configure(text='''Data History''')
        
        #frame to hold treeview and scrollbars
        self.Frame4 = tk.Frame(self.top)
        self.Frame4.place(relx=0.024, rely=0.253, relheight=0.719, relwidth=0.95)
        self.Frame4.configure(relief='groove')
        self.Frame4.configure(borderwidth="2")
        self.Frame4.configure(relief="groove")
        self.Frame4.configure(highlightcolor="Black")

  
        # the treeview widget with columns for displaying data
        self.tree = ttk.Treeview(self.Frame4, columns=("date", "mean_temp", "max_temp", "min_temp", "mean_hum", "max_hum", "min_hum"), show='headings')
        self.tree.heading("date", text="Date")
        self.tree.heading("mean_temp", text="Mean Temp (C)")
        self.tree.heading("max_temp", text="Max Temp (C)")
        self.tree.heading("min_temp", text="Min Temp (C)")
        self.tree.heading("mean_hum", text="Mean Humidity (%)")
        self.tree.heading("max_hum", text="Max Humidity (%)")
        self.tree.heading("min_hum", text="Min Humidity (%)")
        
        # Set column widths and alignment for the treeview
        self.tree.column("date", width=180, anchor='w')
        self.tree.column("mean_temp", width=150, anchor='w')
        self.tree.column("max_temp", width=150, anchor='w')
        self.tree.column("min_temp", width=150, anchor='w')
        self.tree.column("mean_hum", width=150, anchor='w')
        self.tree.column("max_hum", width=150, anchor='w')
        self.tree.column("min_hum", width=150, anchor='w')
        
        # Create scrollbars
        self.vsb = ttk.Scrollbar(self.Frame4, orient="vertical", command=self.tree.yview)
        self.hsb = ttk.Scrollbar(self.Frame4, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)
        
        # Place the treeview and scrollbars within the frame
        self.tree.grid(row=0, column=0, sticky='nsew')
        self.vsb.grid(row=0, column=1, sticky='ns')
        self.hsb.grid(row=1, column=0, sticky='ew')
        
        # Adjust the row and column weights to make sure the Treeview expands with the window
        self.Frame4.grid_rowconfigure(0, weight=1)
        self.Frame4.grid_columnconfigure(0, weight=1)
        
        # Fetch data from the database and insert it into the treeview
        self.load_history_data()

  
    def load_history_data(self):
        # Connect to SQLite database
        conn = sqlite3.connect('sensors.db')
        cursor = conn.cursor()
        
        # Fetch all records from the history table
        cursor.execute('SELECT date, mean_temperature, max_temperature, min_temperature, mean_humidity, max_humidity, min_humidity FROM history')
        rows = cursor.fetchall()
        
        # Insert records into the treeview
        for row in rows:
                formatted_row = (
                    row[0],  # date
                    f"{row[1]:.2f}",  # mean_temperature
                    f"{row[2]:.2f}",  # max_temperature
                    f"{row[3]:.2f}",  # min_temperature
                    f"{row[4]:.2f}",  # mean_humidity
                    f"{row[5]:.2f}",  # max_humidity
                    f"{row[6]:.2f}"   # min_humidity
                )
                self.tree.insert("", "end", values=formatted_row)
    
        # Close the database connection
        conn.close()
#--------------------------------------------------------------------------------
#Functions to make app open and close properly
def on_close():
	if messagebox.askokcancel("Quit", "Do you want to quit?"):
	    GPIO.cleanup()
	    root.quit()
	    root.destroy() 
	
def initialize_gpio():
    GPIO.setwarnings(True)
    GPIO.setmode(GPIO.BCM)
    instance = dht11.DHT11(pin=4)

# Main application entry point
if __name__ == '__main__':
	
    # Your Google Sheets ID
    spreadsheet_id = "12HvdgVRrjt13X6ltcFCL0Hj6tkq0AAwZBulBHkAPHVI"
    
    
    service = get_service()
    
    # Create necessary sheets if they don't exist
    sheet_names = ["RawHistory", "Monitoring", "History"]
    for sheet_name in sheet_names:
        create_sheet_if_not_exists(service, spreadsheet_id, sheet_name)
    
    # Ensure headers exist in each sheet
    ensure_sheet_header(service, spreadsheet_id, "RawHistory", ["Time", "Temperature", "Humidity"])
    ensure_sheet_header(service, spreadsheet_id, "Monitoring", ["Time", "Temperature", "Humidity"])
    ensure_sheet_header(service, spreadsheet_id, "History", ["Time", "Mean Temperature", "Mean Humidity", "Min Temperature", "Min Humidity", "Max Temperature", "Max Humidity"])
  
    initialize_gpio()
	
    #create gui window
    root = tk.Tk()
    root.protocol( 'WM_DELETE_WINDOW' , on_close)
    app = Toplevel1(root)
    root.mainloop()




