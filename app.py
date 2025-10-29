from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/')
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>SK4FiLM Backend</title>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                background: #0a0a0a; 
                color: white; 
                text-align: center; 
                padding: 50px; 
            }
            .status { 
                background: green; 
                color: white; 
                padding: 10px 20px; 
                border-radius: 5px; 
                display: inline-block; 
            }
        </style>
    </head>
    <body>
        <h1>SK4FiLM Backend</h1>
        <div class="status">🟢 STATUS: HEALTHY</div>
        <p>Backend server is running successfully</p>
        <p><a href="/health" style="color: #00ccff;">Health Check</a></p>
    </body>
    </html>
    """

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "service": "SK4FiLM Backend", 
        "timestamp": "2024-01-01T00:00:00Z"
    })

@app.route('/api/health')
def api_health():
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)
