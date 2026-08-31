"""
Advanced Analytics Service - AI-powered insights, suggestions, and analytics
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict, Counter
import json
from sqlalchemy import func, and_

from app.extensions import db
from app.models.user import User
from app.models.generation import Generation
from app.models.image import Image
from app.models.saved_prompt import SavedPrompt
from app.models.collection import Collection
from app.utils import now_utc


class AnalyticsService:
    """Advanced analytics and AI-powered insights for user creativity."""
    
    def __init__(self):
        self.suggestion_cache = {}
    
    def get_user_analytics(self, user_id: int, days: int = 30) -> Dict:
        """
        Get comprehensive analytics for a user.
        
        Args:
            user_id: User ID
            days: Number of days to analyze
            
        Returns:
            Dict with analytics data
        """
        end_date = now_utc()
        start_date = end_date - timedelta(days=days)
        
        # Generation analytics
        generation_stats = self._get_generation_stats(user_id, start_date, end_date)
        
        # Image analytics
        image_stats = self._get_image_stats(user_id, start_date, end_date)
        
        # Prompt analytics
        prompt_stats = self._get_prompt_stats(user_id, start_date, end_date)
        
        # Usage patterns
        usage_patterns = self._analyze_usage_patterns(user_id, start_date, end_date)
        
        # Creative insights
        creative_insights = self._generate_creative_insights(
            user_id, generation_stats, image_stats, prompt_stats
        )
        
        return {
            'period': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat(),
                'days': days
            },
            'generations': generation_stats,
            'images': image_stats,
            'prompts': prompt_stats,
            'usage_patterns': usage_patterns,
            'creative_insights': creative_insights,
            'generated_at': now_utc().isoformat()
        }
    
    def _get_generation_stats(self, user_id: int, start_date: datetime, end_date: datetime) -> Dict:
        """Get generation statistics."""
        generations = Generation.query.filter(
            and_(
                Generation.user_id == user_id,
                Generation.created_at >= start_date,
                Generation.created_at <= end_date
            )
        ).all()
        
        total = len(generations)
        completed = sum(1 for g in generations if g.status == 'completed')
        failed = sum(1 for g in generations if g.status == 'failed')
        
        # Status breakdown
        status_breakdown = Counter(g.status for g in generations)
        
        # Provider usage
        provider_usage = Counter(g.provider for g in generations)
        
        # Model usage
        model_usage = Counter(g.model for g in generations if g.model)
        
        # Daily activity
        daily_activity = defaultdict(int)
        for g in generations:
            date_key = g.created_at.strftime('%Y-%m-%d')
            daily_activity[date_key] += 1
        
        # Average generation time
        completed_with_time = [g for g in generations if g.completed_at and g.status == 'completed']
        avg_time = None
        if completed_with_time:
            total_time = sum((g.completed_at - g.created_at).total_seconds() for g in completed_with_time)
            avg_time = total_time / len(completed_with_time)
        
        return {
            'total': total,
            'completed': completed,
            'failed': failed,
            'success_rate': (completed / total * 100) if total > 0 else 0,
            'status_breakdown': dict(status_breakdown),
            'provider_usage': dict(provider_usage),
            'model_usage': dict(model_usage),
            'daily_activity': dict(daily_activity),
            'average_generation_time': avg_time
        }
    
    def _get_image_stats(self, user_id: int, start_date: datetime, end_date: datetime) -> Dict:
        """Get image statistics."""
        images = Image.query.filter(
            and_(
                Image.user_id == user_id,
                Image.created_at >= start_date,
                Image.created_at <= end_date,
                Image.is_deleted == False
            )
        ).all()
        
        total = len(images)
        
        # Size distribution
        sizes = [(img.width, img.height) for img in images if img.width and img.height]
        size_distribution = Counter(sizes)
        
        # Format distribution
        format_distribution = Counter(img.format for img in images if img.format)
        
        # Aspect ratio distribution
        aspect_ratios = []
        for w, h in sizes:
            if h > 0:
                ratio = round(w / h, 2)
                aspect_ratios.append(ratio)
        aspect_ratio_distribution = Counter(aspect_ratios)
        
        # Favorite images
        favorite_count = sum(1 for img in images if img.is_favorite)
        
        # Images in collections
        collection_usage = sum(len(img.collections) for img in images)
        
        return {
            'total': total,
            'size_distribution': {f"{k[0]}x{k[1]}": v for k, v in size_distribution.items()},
            'format_distribution': dict(format_distribution),
            'aspect_ratio_distribution': dict(aspect_ratio_distribution),
            'favorite_count': favorite_count,
            'in_collections_count': collection_usage,
            'average_resolution': {
                'width': sum(w for w, h in sizes) / len(sizes) if sizes else 0,
                'height': sum(h for w, h in sizes) / len(sizes) if sizes else 0
            }
        }
    
    def _get_prompt_stats(self, user_id: int, start_date: datetime, end_date: datetime) -> Dict:
        """Get prompt statistics."""
        generations = Generation.query.filter(
            and_(
                Generation.user_id == user_id,
                Generation.created_at >= start_date,
                Generation.created_at <= end_date
            )
        ).all()
        
        prompts = [g.prompt for g in generations if g.prompt]
        
        # Prompt length statistics
        prompt_lengths = [len(p) for p in prompts]
        avg_length = sum(prompt_lengths) / len(prompt_lengths) if prompt_lengths else 0
        
        # Word count statistics
        word_counts = [len(p.split()) for p in prompts]
        avg_words = sum(word_counts) / len(word_counts) if word_counts else 0
        
        # Common words
        all_words = []
        for prompt in prompts:
            all_words.extend(prompt.lower().split())
        common_words = Counter(all_words).most_common(20)
        
        # Style usage
        style_usage = Counter()
        for g in generations:
            params = g.parameters or {}
            if params.get('style'):
                style_usage[params['style']] += 1
        
        # Quality usage
        quality_usage = Counter()
        for g in generations:
            params = g.parameters or {}
            if params.get('quality'):
                quality_usage[params['quality']] += 1
        
        return {
            'total_prompts': len(prompts),
            'average_length': round(avg_length, 2),
            'average_words': round(avg_words, 2),
            'common_words': common_words,
            'style_usage': dict(style_usage),
            'quality_usage': dict(quality_usage)
        }
    
    def _analyze_usage_patterns(self, user_id: int, start_date: datetime, end_date: datetime) -> Dict:
        """Analyze user usage patterns."""
        generations = Generation.query.filter(
            and_(
                Generation.user_id == user_id,
                Generation.created_at >= start_date,
                Generation.created_at <= end_date
            )
        ).all()
        
        # Time of day patterns
        hour_activity = defaultdict(int)
        day_activity = defaultdict(int)
        
        for g in generations:
            hour = g.created_at.hour
            day = g.created_at.strftime('%A')
            hour_activity[hour] += 1
            day_activity[day] += 1
        
        # Peak hours
        peak_hours = sorted(hour_activity.items(), key=lambda x: x[1], reverse=True)[:3]
        
        # Peak days
        peak_days = sorted(day_activity.items(), key=lambda x: x[1], reverse=True)[:3]
        
        # Session analysis (generations within 30 minutes)
        sessions = self._identify_sessions(generations)
        
        return {
            'hourly_activity': dict(hour_activity),
            'daily_activity': dict(day_activity),
            'peak_hours': peak_hours,
            'peak_days': peak_days,
            'sessions': {
                'total': len(sessions),
                'average_length': sum(s['duration'] for s in sessions) / len(sessions) if sessions else 0,
                'average_generations': sum(s['count'] for s in sessions) / len(sessions) if sessions else 0
            }
        }
    
    def _identify_sessions(self, generations: List[Generation]) -> List[Dict]:
        """Identify creative sessions from generations."""
        if not generations:
            return []
        
        sorted_gens = sorted(generations, key=lambda g: g.created_at)
        sessions = []
        current_session = {'start': sorted_gens[0].created_at, 'generations': []}
        
        for gen in sorted_gens:
            time_diff = (gen.created_at - current_session['start']).total_seconds()
            
            if time_diff > 1800:  # 30 minutes gap = new session
                if current_session['generations']:
                    sessions.append({
                        'start': current_session['start'].isoformat(),
                        'end': current_session['generations'][-1].created_at.isoformat(),
                        'duration': (current_session['generations'][-1].created_at - current_session['start']).total_seconds(),
                        'count': len(current_session['generations'])
                    })
                current_session = {'start': gen.created_at, 'generations': []}
            
            current_session['generations'].append(gen)
        
        # Add last session
        if current_session['generations']:
            sessions.append({
                'start': current_session['start'].isoformat(),
                'end': current_session['generations'][-1].created_at.isoformat(),
                'duration': (current_session['generations'][-1].created_at - current_session['start']).total_seconds(),
                'count': len(current_session['generations'])
            })
        
        return sessions
    
    def _generate_creative_insights(self, user_id: int, gen_stats: Dict, 
                                   img_stats: Dict, prompt_stats: Dict) -> Dict:
        """Generate AI-powered creative insights."""
        insights = {
            'strengths': [],
            'suggestions': [],
            'trends': [],
            'recommendations': []
        }
        
        # Analyze success rate
        if gen_stats['success_rate'] > 90:
            insights['strengths'].append('High generation success rate - your prompts are well-crafted')
        elif gen_stats['success_rate'] < 70:
            insights['suggestions'].append('Consider improving prompt specificity for better results')
        
        # Analyze prompt complexity
        if prompt_stats['average_words'] > 20:
            insights['strengths'].append('Detailed, complex prompts - good for nuanced results')
        elif prompt_stats['average_words'] < 8:
            insights['suggestions'].append('Try adding more descriptive details to your prompts')
        
        # Analyze style diversity
        if len(prompt_stats['style_usage']) > 3:
            insights['strengths'].append('Diverse style experimentation - creative variety')
        else:
            insights['suggestions'].append('Experiment with different artistic styles')
        
        # Analyze usage patterns
        if gen_stats['daily_activity']:
            most_active_day = max(gen_stats['daily_activity'].items(), key=lambda x: x[1])[0]
            insights['trends'].append(f'Most creative on {most_active_day}')
        
        # Generate personalized recommendations
        insights['recommendations'] = self._generate_recommendations(
            user_id, gen_stats, img_stats, prompt_stats
        )
        
        return insights
    
    def _generate_recommendations(self, user_id: int, gen_stats: Dict, 
                                 img_stats: Dict, prompt_stats: Dict) -> List[str]:
        """Generate personalized recommendations."""
        recommendations = []
        
        # Style recommendations
        if 'photo' not in prompt_stats['style_usage']:
            recommendations.append('Try photorealistic style for more realistic results')
        
        # Quality recommendations
        if 'hd' not in prompt_stats['quality_usage']:
            recommendations.append('Experiment with HD quality for sharper details')
        
        # Aspect ratio recommendations
        common_ratios = list(img_stats.get('aspect_ratio_distribution', {}).keys())
        if len(common_ratios) < 3:
            recommendations.append('Try different aspect ratios for varied compositions')
        
        # Creative suggestions based on common words
        common_words = [word for word, count in prompt_stats.get('common_words', [])]
        creative_themes = {
            'portrait': 'portrait', 'person': 'people', 'character': 'characters',
            'landscape': 'landscape', 'nature': 'nature', 'scene': 'scenes',
            'abstract': 'abstract', 'artistic': 'artistic', 'creative': 'creative'
        }
        
        for word, theme in creative_themes.items():
            if word in common_words:
                recommendations.append(f'Explore more {theme} themes based on your interests')
                break
        
        return recommendations[:5]  # Limit to top 5 recommendations
    
    def get_ai_suggestions(self, user_id: int, context: str = 'general') -> Dict:
        """
        Get AI-powered suggestions based on user behavior and context.
        
        Args:
            user_id: User ID
            context: Context for suggestions ('prompt', 'style', 'composition', etc.)
            
        Returns:
            Dict with AI suggestions
        """
        cache_key = f"{user_id}_{context}"
        
        # Check cache
        if cache_key in self.suggestion_cache:
            cached, timestamp = self.suggestion_cache[cache_key]
            if (now_utc() - timestamp).total_seconds() < 3600:  # 1 hour cache
                return cached
        
        # Generate suggestions based on context
        if context == 'prompt':
            suggestions = self._get_prompt_suggestions(user_id)
        elif context == 'style':
            suggestions = self._get_style_suggestions(user_id)
        elif context == 'composition':
            suggestions = self._get_composition_suggestions(user_id)
        else:
            suggestions = self._get_general_suggestions(user_id)
        
        result = {
            'context': context,
            'suggestions': suggestions,
            'generated_at': now_utc().isoformat()
        }
        
        # Cache result
        self.suggestion_cache[cache_key] = (result, now_utc())
        
        return result
    
    def _get_prompt_suggestions(self, user_id: int) -> List[Dict]:
        """Get prompt enhancement suggestions."""
        # Get user's recent successful prompts
        recent_successful = Generation.query.filter(
            and_(
                Generation.user_id == user_id,
                Generation.status == 'completed'
            )
        ).order_by(Generation.created_at.desc()).limit(10).all()
        
        suggestions = []
        
        # Analyze successful prompts
        if recent_successful:
            avg_length = sum(len(g.prompt) for g in recent_successful) / len(recent_successful)
            
            if avg_length < 100:
                suggestions.append({
                    'type': 'enhancement',
                    'suggestion': 'Try adding more descriptive details to your prompts',
                    'example': 'Instead of "a cat", try "a fluffy orange cat sitting on a windowsill, soft morning light, detailed fur'
                })
        
        # Add creative prompt ideas
        creative_ideas = [
            {
                'type': 'creative',
                'suggestion': 'Try combining contrasting elements',
                'example': 'Futuristic architecture with ancient vines growing on it'
            },
            {
                'type': 'creative',
                'suggestion': 'Experiment with lighting descriptions',
                'example': 'Golden hour lighting with long dramatic shadows'
            },
            {
                'type': 'creative',
                'suggestion': 'Add emotional context to your prompts',
                'example': 'A peaceful mountain lake at dawn, serene and tranquil atmosphere'
            }
        ]
        
        suggestions.extend(creative_ideas)
        
        return suggestions
    
    def _get_style_suggestions(self, user_id: int) -> List[Dict]:
        """Get style suggestions based on user preferences."""
        # Get user's style preferences
        user_styles = db.session.query(
            func.json_extract(Generation.parameters, '$.style')
        ).filter(
            and_(
                Generation.user_id == user_id,
                Generation.status == 'completed'
            )
        ).all()
        
        style_counts = Counter(style[0] for style in user_styles if style[0])
        
        suggestions = []
        
        # Suggest underexplored styles
        all_styles = ['auto', 'photo', 'art', 'paint', 'anime', '3d', 'pixel', 'minimal']
        underexplored = [s for s in all_styles if s not in style_counts or style_counts[s] < 3]
        
        for style in underexplored[:3]:
            suggestions.append({
                'type': 'style_exploration',
                'suggestion': f'Try the {style} style',
                'description': self._get_style_description(style)
            })
        
        return suggestions
    
    def _get_style_description(self, style: str) -> str:
        """Get description for a style."""
        descriptions = {
            'auto': 'AI-optimized style selection',
            'photo': 'Photorealistic images with natural lighting',
            'art': 'Digital art with bold colors and clean lines',
            'paint': 'Traditional painting aesthetic with visible brushstrokes',
            'anime': 'Japanese animation style with vibrant colors',
            '3d': 'Three-dimensional rendered images with depth',
            'pixel': 'Retro pixel art aesthetic',
            'minimal': 'Clean, minimalist design with simple elements'
        }
        return descriptions.get(style, 'Creative artistic style')
    
    def _get_composition_suggestions(self, user_id: int) -> List[Dict]:
        """Get composition suggestions."""
        suggestions = [
            {
                'type': 'composition',
                'suggestion': 'Try the rule of thirds',
                'description': 'Place main elements off-center for more dynamic compositions'
            },
            {
                'type': 'composition',
                'suggestion': 'Experiment with different aspect ratios',
                'description': 'Wide formats for landscapes, tall for portraits'
            },
            {
                'type': 'composition',
                'suggestion': 'Add depth with foreground elements',
                'description': 'Include objects in the foreground to create depth'
            }
        ]
        
        return suggestions
    
    def _get_general_suggestions(self, user_id: int) -> List[Dict]:
        """Get general creative suggestions."""
        return [
            {
                'type': 'discovery',
                'suggestion': 'Explore the gallery for inspiration',
                'action': 'gallery'
            },
            {
                'type': 'learning',
                'suggestion': 'Try the prompt library for starting ideas',
                'action': 'prompts'
            },
            {
                'type': 'experimentation',
                'suggestion': 'Use reference images for style transfer',
                'action': 'editor'
            }
        ]
    
    def get_trending_prompts(self, limit: int = 10) -> List[Dict]:
        """Get trending prompts across all users."""
        # Get recent successful generations
        recent_generations = Generation.query.filter(
            and_(
                Generation.status == 'completed',
                Generation.created_at >= now_utc() - timedelta(days=7)
            )
        ).order_by(Generation.created_at.desc()).limit(100).all()
        
        # Extract and count prompts
        prompt_counter = Counter()
        for gen in recent_generations:
            # Normalize prompt for counting
            normalized = ' '.join(gen.prompt.lower().split())
            prompt_counter[normalized] += 1
        
        # Get top trending
        trending = prompt_counter.most_common(limit)
        
        return [
            {
                'prompt': prompt,
                'frequency': count,
                'related_generations': count
            }
            for prompt, count in trending
        ]
    
    def get_personalized_recommendations(self, user_id: int) -> Dict:
        """Get personalized recommendations based on user behavior."""
        analytics = self.get_user_analytics(user_id, days=30)
        
        recommendations = {
            'prompts': [],
            'styles': [],
            'tools': [],
            'learning': []
        }
        
        # Prompt recommendations based on success patterns
        if analytics['generations']['success_rate'] > 80:
            recommendations['prompts'].append({
                'type': 'advanced',
                'title': 'Try complex prompts',
                'description': 'Your high success rate suggests you\'re ready for more complex prompts'
            })
        
        # Style recommendations
        used_styles = set(analytics['prompts']['style_usage'].keys())
        if len(used_styles) < 4:
            recommendations['styles'].append({
                'type': 'exploration',
                'title': 'Explore new styles',
                'description': 'You\'ve used few styles - try anime, 3d, or minimal styles'
            })
        
        # Tool recommendations
        recommendations['tools'].extend([
            {
                'type': 'tool',
                'title': 'Try the editor',
                'description': 'Enhance your generated images with the built-in editor'
            },
            {
                'type': 'tool',
                'title': 'Create collections',
                'description': 'Organize your best work into themed collections'
            }
        ])
        
        # Learning recommendations
        recommendations['learning'].append({
            'type': 'learning',
            'title': 'Prompt engineering guide',
            'description': 'Learn advanced techniques for better prompts'
        })
        
        return recommendations


# Singleton instance
_analytics_service = None

def get_analytics_service():
    """Get the singleton AnalyticsService instance."""
    global _analytics_service
    if _analytics_service is None:
        _analytics_service = AnalyticsService()
    return _analytics_service