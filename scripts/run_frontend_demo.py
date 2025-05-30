#!/usr/bin/env python3
"""
Demo script to run Kiwi with the new frontend
"""

import sys
import os
from pathlib import Path

# Add the src directory to the Python path
src_dir = Path(__file__).parent / 'src'
sys.path.insert(0, str(src_dir))

try:
    from kiwi.base import VannaBase
    from kiwi.flask_app.frontend_app import create_app
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure you're running this from the project root directory")
    sys.exit(1)


class DemoVanna(VannaBase):
    """Demo Vanna implementation for testing the frontend"""
    
    def __init__(self):
        self.training_data = [
            {"question": "What are the top 10 customers by sales?", "sql": "SELECT customer_name, SUM(sales) as total_sales FROM customers GROUP BY customer_name ORDER BY total_sales DESC LIMIT 10"},
            {"question": "Show me monthly revenue trends", "sql": "SELECT DATE_FORMAT(order_date, '%Y-%m') as month, SUM(revenue) as monthly_revenue FROM orders GROUP BY month ORDER BY month"},
            {"question": "Which products are most popular?", "sql": "SELECT product_name, COUNT(*) as order_count FROM order_items oi JOIN products p ON oi.product_id = p.id GROUP BY product_name ORDER BY order_count DESC"},
            {"question": "What is the average order value?", "sql": "SELECT AVG(total_amount) as avg_order_value FROM orders"},
            {"question": "Show customer distribution by region", "sql": "SELECT region, COUNT(*) as customer_count FROM customers GROUP BY region ORDER BY customer_count DESC"}
        ]
    
    # Required abstract methods implementation
    def add_ddl(self, ddl: str) -> str:
        """Add DDL statement (demo implementation)"""
        return f"Added DDL: {ddl}"
    
    def add_documentation(self, documentation: str) -> str:
        """Add documentation (demo implementation)"""
        return f"Added documentation: {documentation}"
    
    def add_question_sql(self, question: str, sql: str) -> str:
        """Add question-SQL pair (demo implementation)"""
        self.training_data.append({"question": question, "sql": sql})
        return f"Added training pair: {question} -> {sql}"
    
    def assistant_message(self, message: str) -> str:
        """Format assistant message"""
        return f"Assistant: {message}"
    
    def generate_embedding(self, data: str) -> list:
        """Generate embedding (demo implementation)"""
        # Return a dummy embedding
        return [0.1] * 384
    
    def get_related_ddl(self, question: str) -> list:
        """Get related DDL (demo implementation)"""
        return [
            "CREATE TABLE customers (id INT, customer_name VARCHAR(255), region VARCHAR(100));",
            "CREATE TABLE orders (id INT, customer_id INT, order_date DATE, total_amount DECIMAL(10,2));"
        ]
    
    def get_related_documentation(self, question: str) -> list:
        """Get related documentation (demo implementation)"""
        return [
            "The customers table contains customer information including name and region.",
            "The orders table tracks all customer orders with dates and amounts."
        ]
    
    def get_similar_question_sql(self, question: str) -> list:
        """Get similar question-SQL pairs (demo implementation)"""
        return [
            {"question": "What are the top customers?", "sql": "SELECT customer_name FROM customers ORDER BY sales DESC"},
            {"question": "Show revenue by month", "sql": "SELECT month, revenue FROM monthly_revenue"}
        ]
    
    def remove_training_data(self, id: str) -> bool:
        """Remove training data (demo implementation)"""
        return True
    
    def submit_prompt(self, prompt: str) -> str:
        """Submit prompt to LLM (demo implementation)"""
        return f"LLM Response to: {prompt}"
    
    def system_message(self, message: str) -> str:
        """Format system message"""
        return f"System: {message}"
    
    def user_message(self, message: str) -> str:
        """Format user message"""
        return f"User: {message}"
    
    def generate_sql(self, question, **kwargs):
        """Generate SQL for a given question"""
        # Simple demo implementation
        question_lower = question.lower()
        
        if "customer" in question_lower and "top" in question_lower:
            return "SELECT customer_name, SUM(sales) as total_sales FROM customers GROUP BY customer_name ORDER BY total_sales DESC LIMIT 10;"
        elif "revenue" in question_lower or "sales" in question_lower:
            return "SELECT DATE_FORMAT(order_date, '%Y-%m') as month, SUM(revenue) as monthly_revenue FROM orders GROUP BY month ORDER BY month;"
        elif "product" in question_lower:
            return "SELECT product_name, COUNT(*) as order_count FROM order_items oi JOIN products p ON oi.product_id = p.id GROUP BY product_name ORDER BY order_count DESC;"
        elif "average" in question_lower:
            return "SELECT AVG(total_amount) as avg_order_value FROM orders;"
        elif "region" in question_lower:
            return "SELECT region, COUNT(*) as customer_count FROM customers GROUP BY region ORDER BY customer_count DESC;"
        else:
            return f"-- Generated SQL for: {question}\nSELECT 'This is a demo response' as message, '{question}' as original_question;"
    
    def is_sql_valid(self, sql):
        """Check if SQL is valid (demo always returns True)"""
        return sql and len(sql.strip()) > 0
    
    def run_sql(self, sql):
        """Run SQL and return demo results"""
        # Return demo data based on the SQL
        if "customer" in sql.lower():
            return [
                {"customer_name": "Acme Corp", "total_sales": 150000},
                {"customer_name": "Tech Solutions", "total_sales": 125000},
                {"customer_name": "Global Industries", "total_sales": 98000},
                {"customer_name": "Innovation Labs", "total_sales": 87000},
                {"customer_name": "Future Systems", "total_sales": 76000}
            ]
        elif "revenue" in sql.lower() or "month" in sql.lower():
            return [
                {"month": "2024-01", "monthly_revenue": 245000},
                {"month": "2024-02", "monthly_revenue": 267000},
                {"month": "2024-03", "monthly_revenue": 298000},
                {"month": "2024-04", "monthly_revenue": 312000},
                {"month": "2024-05", "monthly_revenue": 334000}
            ]
        elif "product" in sql.lower():
            return [
                {"product_name": "Premium Widget", "order_count": 1250},
                {"product_name": "Standard Widget", "order_count": 980},
                {"product_name": "Deluxe Widget", "order_count": 756},
                {"product_name": "Basic Widget", "order_count": 543},
                {"product_name": "Economy Widget", "order_count": 432}
            ]
        elif "average" in sql.lower():
            return [{"avg_order_value": 1247.83}]
        elif "region" in sql.lower():
            return [
                {"region": "North America", "customer_count": 1245},
                {"region": "Europe", "customer_count": 987},
                {"region": "Asia Pacific", "customer_count": 756},
                {"region": "Latin America", "customer_count": 432},
                {"region": "Middle East", "customer_count": 234}
            ]
        else:
            return [
                {"message": "This is a demo response", "original_question": sql},
                {"note": "In a real implementation, this would execute against your database"}
            ]
    
    def get_training_data(self):
        """Return training data"""
        import pandas as pd
        return pd.DataFrame(self.training_data)
    
    def generate_plotly_figure(self, question, sql, df):
        """Generate a Plotly figure (demo implementation)"""
        # Return a simple demo chart configuration
        return {
            "data": [
                {
                    "x": ["Jan", "Feb", "Mar", "Apr", "May"],
                    "y": [245000, 267000, 298000, 312000, 334000],
                    "type": "bar",
                    "name": "Revenue"
                }
            ],
            "layout": {
                "title": f"Demo Chart for: {question}",
                "xaxis": {"title": "Month"},
                "yaxis": {"title": "Revenue ($)"}
            }
        }


def main():
    """Main function to run the demo"""
    print("🥝 Starting Kiwi Frontend Demo...")
    
    # Create demo Vanna instance
    vn = DemoVanna()
    
    # Create the Flask app with modern frontend
    app = create_app(
        vn=vn,
        debug=True,
        use_modern_frontend=True,
        title="Kiwi SQL Assistant - Demo",
        subtitle="Experience the power of AI-driven SQL generation",
        allow_llm_to_see_data=True
    )
    
    # Run the app
    import socket
    
    # Find an available port
    def find_free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            s.listen(1)
            port = s.getsockname()[1]
        return port
    
    port = find_free_port()
    print(f"🚀 Starting server on port {port}...")
    
    try:
        app.run(
            host="0.0.0.0",  # Allow external connections
            port=port,       # Use a free port
            debug=True
        )
    except KeyboardInterrupt:
        print("\n👋 Shutting down Kiwi Frontend Demo...")
    except Exception as e:
        print(f"❌ Error running the app: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()