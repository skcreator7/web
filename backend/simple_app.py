from quart import Quart, jsonify

app = Quart(__name__)

@app.route('/')
async def home():
    return jsonify({"status": "healthy", "message": "SK4FiLM API"})

@app.route('/health')
async def health():
    return jsonify({"status": "healthy"})

@app.route('/api/health')
async def api_health():
    return jsonify({"status": "healthy"})

@app.route('/api/search')
async def api_search():
    return jsonify({
        "status": "success",
        "query": "test",
        "results": [],
        "count": 0,
        "message": "Backend is starting..."
    })

@app.route('/api/latest_posters')
async def api_latest_posters():
    return jsonify({
        "status": "success", 
        "posters": [],
        "count": 0,
        "message": "Backend is starting..."
    })

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8000)
