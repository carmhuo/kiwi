from react_app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True, port=2025, use_reloader=False)