from app import create_app

app = create_app()

if __name__ == "__main__":
    # host=0.0.0.0 so you can open it from your phone on the same wifi
    app.run(host="0.0.0.0", port=5001, debug=True)
