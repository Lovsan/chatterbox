# Chatterbox

**⚠️⚠️⚠️ CHATTERBOX IS CURRENTLY UNDER ACTIVE DEVELOPMENT, AND THE DOCUMENTATION MAY NOT BE FULLY UP-TO-DATE. LAST DOCUMENTATION UPDATE: 6.12.2024 ⚠️⚠️⚠️**

Chatterbox is a simple real-time chat application built using Python, Flask, SQL, HTML, CSS (with Bootstrap), and JavaScript. It allows users to register, log in, and send messages to a chatroom.

## Features

- **User Authentication**: Users can register, log in, and log out.
- **Real-Time Messaging**: Chat functionality where messages are saved to a database and displayed in real-time.
- **Bootstrap UI**: A responsive and clean interface styled using Bootstrap.
- **Database**: SQLite is used to store user credentials and chat messages.

## Technologies Used

- **Backend**: Python 3, Flask, Flask-SQLAlchemy, Flask-Session
- **Frontend**: HTML, CSS (Bootstrap), JavaScript
- **Database**: SQLite
- **Environment**: Docker-based devcontainer for isolated development

## Installation

### Prerequisites

- Python 3.10+
- Docker (if using the devcontainer setup)

### Setup

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

### Using Docker and Devcontainer

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
Chatterbox/
│
├── app.py                # Main application logic
├── models.py             # Database models
├── init_db.py            # Database initialization script
├── requirements.txt      # Python dependencies
├── helpers.py            # Helper functions and decorators
├── .gitignore            # Gitignore file
├── README.md             # This file
├── instance/
│   └── chatterbox.db     # SQLite database file
├── templates/            # HTML templates
│   ├── layout.html       # Base layout template
│   ├── home.html         # Homepage template
│   ├── login.html        # Login page template
│   ├── register.html     # Registration page template
│   ├── chat.html         # Chat page template
│   └── author.html       # Information about author
├── static/               # Static files
│   ├── scripts.js        # JS for the website
│   └── styles.css        # CSS for the website
└── .devcontainer/
    └── devcontainer.json # Devcontainer configuration
```

## Future Enhancements

- **Real-Time Messaging**: Implement real-time updates using Flask-SocketIO.
- **User Profiles**: Add user profile pages and the ability to update account details.
- **Enhanced UI**: Improve the design and usability of the chat interface.
- **Deployment**: Host the application on a VPS using Docker and Nginx.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Harvard's CS50x course for inspiration and foundational knowledge.
- The Flask and Bootstrap communities for providing excellent documentation and tools.

## Author
Filip Rokita  
[www.filiprokita.com](https://www.filiprokita.com/)

---

Happy coding! 🎉
