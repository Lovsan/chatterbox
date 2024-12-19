# Chatterbox

<div align="center">
   <img src="misc/mockup.png" width="500">
</div>

---

**⚠️⚠️⚠️ CHATTERBOX IS CURRENTLY UNDER ACTIVE DEVELOPMENT, AND THE DOCUMENTATION MAY NOT BE FULLY UP-TO-DATE. LAST DOCUMENTATION UPDATE: 18.12.2024 ⚠️⚠️⚠️**

Chatterbox is a simple real-time chat application built using Python, Flask SQL, JavaScript, HTML, and CSS (with Bootstrap). It allows users to register, log in, and send messages to a chatroom.

## Features

- **User Authentication**: Users can register, log in, and log out.
- **Real-Time Messaging**: Chat functionality where messages are saved to a database and displayed in real-time.
- **Responsive Design**: A clean and adaptable user interface.
- **Database**: SQL is used to store user credentials and chat messages.

## Technologies Used

- **Backend**: Python 3, Flask, SQLAlchemy, Socket.IO, JavaScript
- **Frontend**: HTML, CSS, Bootstrap, JavaScript
- **Database**: SQLite
- **Environment**: Docker-based devcontainer for isolated development

## Installation

### Prerequisites

- Python 3.10+
- Docker (optional)

### Setup using Gunicorn (eg. using Render)
1. **Build Command**
   ```bash
   pip3 install -r requirements.txt && python3 init_db.py -f
   ```
2. **Start Command**
   ```bash
   gunicorn app:app
   ```

### Basic setup (for development)

1. **Install Dependencies**:
   ```bash
   pip3 install -r requirements.txt
   ```

2. **Initialize the Database**:
   ```bash
   python3 init_db.py
   ```

3. **Run the Application**:
   ```bash
   python3 app.py
   ```
   The application will be accessible at [http://127.0.0.1:5000](http://127.0.0.1:5000).

### Setup Using Docker and Devcontainer (for development)

1. Open the project in a development environment that supports Devcontainers (e.g., Visual Studio Code).
2. Follow prompts to build and open the container.
3. The enviroment will be set up automatically based on the `devcontainer.json`.
4. Run `python3 init_db.py`, and then `python3 app.py`.

## Usage

1. Open the application in your browser.
2. Register a new user account.
3. Log in using your credentials.
4. Navigate to the chatroom and start chatting!

## File Structure

```
chatterbox/
│
├── app.py                # Main application logic
├── models.py             # Database models
├── init_db.py            # Database initialization script
├── requirements.txt      # Python dependencies
├── helpers.py            # Helper functions and decorators
├── event_handlers.py     # Event handling logic
├── .gitignore            # Gitignore file
├── README.md             # Project documentation
├── LICENSE               # Project license
│
├── instance/
│   └── chatterbox.db     # SQLite database file
│
├── templates/            # HTML templates
│   ├── layout.html       # Base layout template
│   ├── home.html         # Homepage template
│   ├── login.html        # Login page template
│   ├── register.html     # Registration page template
│   ├── chat.html         # Chat page template
│   └── author.html       # Author information page
│
├── static/               # Static files
│   ├── favicon.ico       # Favicon
│   ├── logo.png          # Logo image
│   ├── scripts.js        # JavaScript for the website
│   ├── websocket.js      # WebSocket JavaScript
│   └── styles.css        # CSS for styling
│
├── misc/                 # Miscellaneous files
│
└── .devcontainer/        # Dev container configuration
```

## Future Enhancements

- **User Profiles**: Add user profile pages and the ability to update account details.
- **Enhanced UI**: Improve the design and usability of the chat interface.
- **React Front-End (Optional)**: Migrate the front-end to React for a more dynamic and modern user experience.
- **Deployment**: Host the application on a VPS using Docker and Nginx.

## Known Bugs
- The users panel (in "Chat" tab) does not update in real time when a message is received from someone other than the current chat participant.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Harvard's CS50x course for inspiration and foundational knowledge.
- The Flask and Bootstrap communities for providing excellent documentation and tools.

## Author
Filip Rokita  
[www.filiprokita.com](https://www.filiprokita.com/)
