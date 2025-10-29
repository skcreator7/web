from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({
        "status": "healthy", 
        "message": "SK4FiLM Backend is running!",
        "service": "Movie Search API"
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

@app.route('/api/health') 
def api_health():
    return jsonify({"status": "healthy"})

@app.route('/api/search')
def api_search():
    return jsonify({
        "status": "success",
        "message": "Search API is working",
        "results": []
    })

@app.route('/api/latest_posters')
def api_latest_posters():
    return jsonify({
        "status": "success", 
        "message": "Posters API is working",
        "posters": []
    })

if __name__ == '__main__':
    print("🚀 Starting SK4FiLM Backend Server...")
    app.run(host='0.0.0.0', port=8000, debug=False)
