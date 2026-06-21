"""
Production-Grade AI Management System
Implements prompt versioning, cost tracking, quality evaluation, and model fallbacks
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import json
import hashlib
from sqlalchemy import Column, String, Float, Integer, DateTime, JSON, Text
from sqlalchemy.orm import Session
from infrastructure.cache import LLMCache, cache
from config.settings import settings
from infrastructure.monitoring import structured_logger, llm_requests_total, llm_cost_usd
try:
    import anthropic  # type: ignore[import-untyped]
except ImportError:
    anthropic = None
try:
    from groq import Groq
except ImportError:
    Groq = None
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


# ==================== PROMPT VERSIONING ====================

class PromptVersion(BaseModel):
    """Versioned prompt template"""
    name: str
    version: str
    template: str
    variables: List[str]
    model: str
    temperature: float = 0.7
    max_tokens: int = 1000
    evaluation_metrics: Dict[str, float] = {}
    created_at: datetime = datetime.now(timezone.utc)


class PromptManager:
    """Manage prompt versions and A/B testing"""
    
    def __init__(self):
        self.prompts: Dict[str, Dict[str, PromptVersion]] = {}
    
    def save_prompt(
        self,
        name: str,
        template: str,
        version: str,
        variables: List[str],
        model: str = "gpt-4",
        **kwargs
    ):
        """Save a new prompt version"""
        prompt_version = PromptVersion(
            name=name,
            version=version,
            template=template,
            variables=variables,
            model=model,
            **kwargs
        )
        
        if name not in self.prompts:
            self.prompts[name] = {}
        
        self.prompts[name][version] = prompt_version
        
        # Cache the prompt
        cache_key = f"prompt:{name}:{version}"
        cache.set(cache_key, prompt_version.dict(), ttl=86400 * 7)
        
        return prompt_version
    
    def get_prompt(self, name: str, version: str = "latest") -> Optional[PromptVersion]:
        """Get a specific prompt version"""
        # Check cache first
        cache_key = f"prompt:{name}:{version}"
        cached = cache.get(cache_key)
        if cached:
            return PromptVersion(**cached)
        
        # Check in-memory store
        if name in self.prompts:
            if version == "latest":
                # Get the latest version
                versions = sorted(self.prompts[name].keys(), reverse=True)
                if versions:
                    return self.prompts[name][versions[0]]
            elif version in self.prompts[name]:
                return self.prompts[name][version]
        
        return None
    
    def render_prompt(self, name: str, version: str, **variables) -> str:
        """Render a prompt with variables"""
        prompt = self.get_prompt(name, version)
        if not prompt:
            raise ValueError(f"Prompt {name} version {version} not found")
        
        return prompt.template.format(**variables)
    
    def compare_versions(self, name: str, version_a: str, version_b: str) -> Dict:
        """Compare two prompt versions"""
        prompt_a = self.get_prompt(name, version_a)
        prompt_b = self.get_prompt(name, version_b)
        
        if not prompt_a or not prompt_b:
            raise ValueError("One or both versions not found")
        
        return {
            "version_a": version_a,
            "version_b": version_b,
            "metrics_a": prompt_a.evaluation_metrics,
            "metrics_b": prompt_b.evaluation_metrics,
            "winner": version_a if sum(prompt_a.evaluation_metrics.values()) > sum(prompt_b.evaluation_metrics.values()) else version_b
        }


# ==================== COST TRACKING ====================

class LLMUsage(BaseModel):
    """Track LLM usage and costs"""
    request_id: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    cached: bool
    latency_ms: float
    timestamp: datetime = datetime.now(timezone.utc)


class CostTracker:
    """Track and analyze LLM costs"""
    
    # Pricing per 1K tokens (as of 2024)
    PRICING = {
        "gpt-4": {"input": 0.03, "output": 0.06},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
        "claude-3-opus": {"input": 0.015, "output": 0.075},
        "claude-3-sonnet": {"input": 0.003, "output": 0.015},
        "llama-3-70b": {"input": 0.0, "output": 0.0},  # Groq free tier
    }
    
    def __init__(self):
        self.usage_history: List[LLMUsage] = []
    
    def calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate cost for LLM usage"""
        if model not in self.PRICING:
            return 0.0
        
        pricing = self.PRICING[model]
        
        input_cost = (prompt_tokens / 1000) * pricing["input"]
        output_cost = (completion_tokens / 1000) * pricing["output"]
        
        return input_cost + output_cost
    
    def record_usage(
        self,
        model: str,
        provider: str,
        prompt_tokens: int,
        completion_tokens: int,
        cached: bool = False,
        latency_ms: float = 0.0
    ) -> LLMUsage:
        """Record LLM usage"""
        request_id = hashlib.md5(
            f"{datetime.now(timezone.utc).isoformat()}{model}".encode()
        ).hexdigest()
        
        cost_usd = self.calculate_cost(model, prompt_tokens, completion_tokens)
        
        usage = LLMUsage(
            request_id=request_id,
            model=model,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=cost_usd,
            cached=cached,
            latency_ms=latency_ms
        )
        
        self.usage_history.append(usage)
        
        # Log to monitoring
        structured_logger.log_llm_request(
            model=model,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            duration=latency_ms / 1000,
            cached=cached
        )
        
        # Store in cache for analytics
        cache_key = f"llm_usage:{request_id}"
        cache.set(cache_key, usage.dict(), ttl=86400 * 30)  # Keep 30 days
        
        return usage
    
    def get_total_cost(self, days: int = 30) -> float:
        """Get total cost for period"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        total = sum(
            usage.cost_usd
            for usage in self.usage_history
            if usage.timestamp >= cutoff
        )
        
        return total
    
    def get_cost_by_model(self, days: int = 30) -> Dict[str, float]:
        """Get cost breakdown by model"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        costs = {}
        for usage in self.usage_history:
            if usage.timestamp >= cutoff:
                if usage.model not in costs:
                    costs[usage.model] = 0.0
                costs[usage.model] += usage.cost_usd
        
        return costs
    
    def get_cache_savings(self) -> float:
        """Calculate money saved from caching"""
        # Estimate: cached requests would have cost the same as non-cached
        cached_requests = [u for u in self.usage_history if u.cached]
        return sum(u.cost_usd for u in cached_requests)


# ==================== QUALITY EVALUATION ====================

class EvaluationMetrics(BaseModel):
    """Metrics for evaluating LLM output quality"""
    relevance_score: float  # 0-1
    accuracy_score: float  # 0-1
    completeness_score: float  # 0-1
    ats_score: Optional[float] = None  # For resumes
    keyword_match: Optional[float] = None  # For job matching
    overall_score: float
    
    def calculate_overall(self):
        """Calculate overall score"""
        scores = [self.relevance_score, self.accuracy_score, self.completeness_score]
        if self.ats_score is not None:
            scores.append(self.ats_score)
        if self.keyword_match is not None:
            scores.append(self.keyword_match)
        
        self.overall_score = sum(scores) / len(scores)


class QualityEvaluator:
    """Evaluate LLM output quality"""
    
    @staticmethod
    def evaluate_resume(resume_text: str, job_description: str) -> EvaluationMetrics:
        """Evaluate resume quality"""
        # Extract keywords from job description
        job_keywords = set(job_description.lower().split())
        resume_keywords = set(resume_text.lower().split())
        
        # Keyword match score
        matching_keywords = job_keywords.intersection(resume_keywords)
        keyword_match = len(matching_keywords) / len(job_keywords) if job_keywords else 0.0
        
        # ATS score (simplified)
        ats_score = QualityEvaluator._calculate_ats_score(resume_text)
        
        metrics = EvaluationMetrics(
            relevance_score=keyword_match,
            accuracy_score=0.8,  # Would use more sophisticated checking
            completeness_score=0.9 if len(resume_text) > 500 else 0.5,
            ats_score=ats_score,
            keyword_match=keyword_match,
            overall_score=0.0
        )
        
        metrics.calculate_overall()
        return metrics
    
    @staticmethod
    def _calculate_ats_score(resume_text: str) -> float:
        """Calculate ATS compatibility score"""
        score = 100.0
        
        # Deduct for ATS-unfriendly elements
        if '<table>' in resume_text.lower():
            score -= 20
        if 'header' in resume_text.lower() or 'footer' in resume_text.lower():
            score -= 10
        if len(resume_text) > 5000:
            score -= 5
        if len(resume_text) < 300:
            score -= 15
        
        return max(0.0, score / 100.0)
    
    @staticmethod
    def evaluate_cover_letter(letter: str, job_description: str) -> EvaluationMetrics:
        """Evaluate cover letter quality"""
        # Check structure
        has_greeting = any(word in letter.lower() for word in ['dear', 'hello', 'hi'])
        has_closing = any(word in letter.lower() for word in ['sincerely', 'regards', 'best'])
        has_company_name = True  # Would extract from job_description
        
        structure_score = (
            (0.3 if has_greeting else 0.0) +
            (0.3 if has_closing else 0.0) +
            (0.4 if has_company_name else 0.0)
        )
        
        # Length check
        word_count = len(letter.split())
        length_score = 1.0 if 250 <= word_count <= 400 else 0.6
        
        metrics = EvaluationMetrics(
            relevance_score=structure_score,
            accuracy_score=0.85,
            completeness_score=length_score,
            overall_score=0.0
        )
        
        metrics.calculate_overall()
        return metrics


# ==================== MODEL ROUTER & FALLBACK ====================

class ModelRouter:
    """Intelligent model routing and fallback"""
    
    def __init__(self):
        groq_key = getattr(settings, "groq_api_key", None)
        openai_key = getattr(settings, "openai_api_key", None)
        self.groq_client = Groq(api_key=groq_key) if groq_key and Groq else None
        self.openai_client = OpenAI(api_key=openai_key) if openai_key and OpenAI else None
        self.cost_tracker = CostTracker()
    
    async def complete(
        self,
        prompt: str,
        model: str = "llama-3-70b",
        temperature: float = 0.7,
        max_tokens: int = 1000,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Smart LLM completion with caching and fallback
        """
        import time
        
        # Check cache first
        if use_cache:
            cached_response = LLMCache.get_response(prompt, model)
            if cached_response:
                return {
                    "response": cached_response["response"],
                    "cached": True,
                    "cost_usd": 0.0,
                    "model": model
                }
        
        start_time = time.time()
        
        try:
            # Try primary model
            result = await self._call_model(prompt, model, temperature, max_tokens)
            
            latency_ms = (time.time() - start_time) * 1000
            
            # Track usage
            self.cost_tracker.record_usage(
                model=model,
                provider=self._get_provider(model),
                prompt_tokens=result["prompt_tokens"],
                completion_tokens=result["completion_tokens"],
                cached=False,
                latency_ms=latency_ms
            )
            
            # Cache the response
            if use_cache:
                LLMCache.set_response(
                    prompt=prompt,
                    model=model,
                    response=result["response"],
                    cost_usd=result["cost_usd"]
                )
            
            return result
            
        except Exception as e:
            # Fallback to alternative model
            structured_logger.log_error(
                error_type="llm_failure",
                component="model_router",
                message=f"Primary model {model} failed, falling back",
                exception=e
            )
            
            fallback_model = self._get_fallback_model(model)
            return await self.complete(prompt, fallback_model, temperature, max_tokens, use_cache)
    
    async def _call_model(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int
    ) -> Dict[str, Any]:
        """Call specific LLM model"""
        provider = self._get_provider(model)
        
        if provider == "groq":
            return await self._call_groq(prompt, model, temperature, max_tokens)
        elif provider == "openai":
            return await self._call_openai(prompt, model, temperature, max_tokens)
        else:
            raise ValueError(f"Unknown provider for model {model}")
    
    async def _call_groq(self, prompt: str, model: str, temperature: float, max_tokens: int) -> Dict:
        """Call Groq API"""
        if self.groq_client is None:
            raise ValueError("Groq API key not configured")
        response = self.groq_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens
        )
        usage = response.usage
        if usage is None:
            raise ValueError("No usage data in Groq response")
        if not response.choices:
            raise ValueError("Empty choices list in Groq response")
        return {
            "response": response.choices[0].message.content,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "cost_usd": 0.0,  # Groq free tier
            "model": model,
            "cached": False
        }
    
    async def _call_openai(self, prompt: str, model: str, temperature: float, max_tokens: int) -> Dict:
        """Call OpenAI API"""
        if not self.openai_client:
            raise ValueError("OpenAI API key not configured")
        
        response = self.openai_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        usage = response.usage
        if usage is None:
            raise ValueError("No usage data in OpenAI response")
        if not response.choices:
            raise ValueError("Empty choices list in OpenAI response")
        cost_usd = self.cost_tracker.calculate_cost(
            model=model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens
        )

        return {
            "response": response.choices[0].message.content,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "cost_usd": cost_usd,
            "model": model,
            "cached": False
        }
    
    def _get_provider(self, model: str) -> str:
        """Get provider for model"""
        if "llama" in model.lower() or "mixtral" in model.lower():
            return "groq"
        elif "gpt" in model.lower():
            return "openai"
        elif "claude" in model.lower():
            return "anthropic"
        else:
            return "groq"  # Default
    
    def _get_fallback_model(self, model: str) -> str:
        """Get fallback model"""
        fallbacks = {
            "gpt-4": "gpt-3.5-turbo",
            "gpt-3.5-turbo": "llama-3-70b",
            "llama-3-70b": "llama-3-8b",
        }
        return fallbacks.get(model, "llama-3-8b")


# ==================== A/B TESTING ====================

class ABTestManager:
    """Manage A/B tests for prompts and models"""
    
    def __init__(self):
        self.experiments: Dict[str, Dict] = {}
    
    def create_experiment(
        self,
        name: str,
        variant_a: Dict,
        variant_b: Dict,
        traffic_split: float = 0.5
    ):
        """Create A/B test experiment"""
        self.experiments[name] = {
            "variant_a": variant_a,
            "variant_b": variant_b,
            "traffic_split": traffic_split,
            "results_a": [],
            "results_b": []
        }
    
    def get_variant(self, experiment_name: str, user_id: str) -> str:
        """Get variant for user (deterministic)"""
        if experiment_name not in self.experiments:
            return "a"
        
        # Hash user_id to determine variant
        hash_value = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
        
        split = self.experiments[experiment_name]["traffic_split"]
        
        return "a" if (hash_value % 100) < (split * 100) else "b"
    
    def record_result(self, experiment_name: str, variant: str, metrics: EvaluationMetrics):
        """Record experiment result"""
        if experiment_name not in self.experiments:
            return
        
        key = f"results_{variant}"
        self.experiments[experiment_name][key].append(metrics)
    
    def analyze_experiment(self, experiment_name: str) -> Dict:
        """Analyze experiment results"""
        if experiment_name not in self.experiments:
            return {}
        
        exp = self.experiments[experiment_name]
        
        results_a = exp["results_a"]
        results_b = exp["results_b"]
        
        avg_score_a = sum(r.overall_score for r in results_a) / len(results_a) if results_a else 0
        avg_score_b = sum(r.overall_score for r in results_b) / len(results_b) if results_b else 0
        
        return {
            "variant_a_score": avg_score_a,
            "variant_b_score": avg_score_b,
            "winner": "a" if avg_score_a > avg_score_b else "b",
            "confidence": abs(avg_score_a - avg_score_b),
            "sample_size_a": len(results_a),
            "sample_size_b": len(results_b)
        }


# Global instances
prompt_manager = PromptManager()
cost_tracker = CostTracker()
quality_evaluator = QualityEvaluator()
model_router = ModelRouter()
ab_test_manager = ABTestManager()
