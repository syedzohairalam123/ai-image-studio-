"""
Analytics API Routes - Advanced analytics and AI-powered suggestions
"""
from flask import jsonify, request
from flask_login import login_required, current_user

from app.routes import api_bp
from app.services.analytics_service import get_analytics_service


@api_bp.route("/analytics/user", methods=["GET"])
@login_required
def get_user_analytics():
    """Get comprehensive analytics for current user."""
    try:
        days = request.args.get('days', 30, type=int)
        
        if days < 1 or days > 365:
            return jsonify({'error': 'Days must be between 1 and 365'}), 400
        
        analytics_service = get_analytics_service()
        analytics = analytics_service.get_user_analytics(current_user.id, days)
        
        return jsonify({
            'success': True,
            'analytics': analytics
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route("/analytics/suggestions", methods=["GET"])
@login_required
def get_ai_suggestions():
    """Get AI-powered suggestions."""
    try:
        context = request.args.get('context', 'general')
        
        analytics_service = get_analytics_service()
        suggestions = analytics_service.get_ai_suggestions(current_user.id, context)
        
        return jsonify({
            'success': True,
            'suggestions': suggestions
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route("/analytics/trending", methods=["GET"])
@login_required
def get_trending_prompts():
    """Get trending prompts across all users."""
    try:
        limit = request.args.get('limit', 10, type=int)
        
        if limit < 1 or limit > 50:
            return jsonify({'error': 'Limit must be between 1 and 50'}), 400
        
        analytics_service = get_analytics_service()
        trending = analytics_service.get_trending_prompts(limit)
        
        return jsonify({
            'success': True,
            'trending': trending
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route("/analytics/recommendations", methods=["GET"])
@login_required
def get_personalized_recommendations():
    """Get personalized recommendations."""
    try:
        analytics_service = get_analytics_service()
        recommendations = analytics_service.get_personalized_recommendations(current_user.id)
        
        return jsonify({
            'success': True,
            'recommendations': recommendations
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route("/analytics/insights", methods=["GET"])
@login_required
def get_creative_insights():
    """Get creative insights for the current user."""
    try:
        days = request.args.get('days', 30, type=int)
        
        analytics_service = get_analytics_service()
        analytics = analytics_service.get_user_analytics(current_user.id, days)
        
        return jsonify({
            'success': True,
            'insights': analytics['creative_insights'],
            'usage_patterns': analytics['usage_patterns']
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500