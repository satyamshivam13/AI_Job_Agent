"""
AI Agents Implementation using CrewAI
Multi-agent system for autonomous job applications
"""

from crewai import Agent, Task, Crew, Process, LLM
from typing import Dict, List, Optional
import json

from config.settings import settings
from config.prompts import AGENT_PROMPTS


class LLMFactory:
    """Factory for creating LLM instances based on configuration"""

    @staticmethod
    def create_llm(provider: Optional[str] = None, temperature: float = 0.7):
        """Create crewai-native LLM instance based on provider"""
        provider = provider or settings.llm_provider.value

        if provider == "groq":
            return LLM(
                model="groq/llama-3.3-70b-versatile",
                api_key=settings.groq_api_key,
                temperature=temperature,
                max_tokens=4096,
            )
        elif provider == "openai":
            return LLM(
                model="gpt-4o-mini",
                api_key=settings.openai_api_key,
                temperature=temperature,
                max_tokens=4096,
            )
        elif provider == "anthropic":
            return LLM(
                model="anthropic/claude-haiku-4-5-20251001",
                api_key=settings.anthropic_api_key,
                temperature=temperature,
                max_tokens=4096,
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")


class JobFinderAgent:
    """Agent responsible for finding and scoring job opportunities"""
    
    def __init__(self, llm=None):
        self.llm = llm or LLMFactory.create_llm(temperature=0.3)  # Lower temp for scoring
        self.agent = self._create_agent()
    
    def _create_agent(self) -> Agent:
        """Create the CrewAI agent"""
        prompts = AGENT_PROMPTS["job_finder"]
        
        return Agent(
            role=prompts["role"],
            goal=prompts["goal"],
            backstory=prompts["backstory"],
            llm=self.llm,
            verbose=True,
            allow_delegation=False,
            max_iter=5
        )
    
    def create_task(self, jobs: List[Dict], user_profile: Dict) -> Task:
        """Create a task for the agent to score jobs"""
        prompts = AGENT_PROMPTS["job_finder"]
        
        task_description = f"""
        {prompts["task"]}
        
        **Candidate Profile:**
        - Name: {user_profile.get('name', 'Unknown')}
        - Target Roles: {', '.join(user_profile.get('target_roles', []))}
        - Primary Skills: {', '.join(user_profile.get('skills', {}).get('primary', []))}
        - Preferred Locations: {', '.join(user_profile.get('locations', {}).get('preferred', []))}
        - Min Salary: {user_profile.get('salary', {}).get('minimum_usd', 0)} USD
        - Experience: {user_profile.get('experience_level', 'entry_level')}
        
        **Jobs to Analyze:**
        {json.dumps(jobs, indent=2)}
        
        Provide your analysis as a JSON array of scored jobs.
        """
        
        return Task(
            description=task_description,
            agent=self.agent,
            expected_output="JSON array of scored jobs with recommendations"
        )
    
    def calculate_match_score(self, job: Dict, user_skills: List[str]) -> float:
        """Keyword-based match score (0–100) without LLM, for fast pre-filtering."""
        if not user_skills:
            return 0.0
        text = " ".join([
            job.get("title", ""),
            job.get("description", ""),
            job.get("company", ""),
        ]).lower()
        matched = sum(1 for skill in user_skills if skill.lower() in text)
        return round(min(matched / len(user_skills) * 100, 100), 1)

    def score_jobs(self, jobs: List[Dict], user_profile: Dict) -> List[Dict]:
        """Score and rank jobs"""
        task = self.create_task(jobs, user_profile)
        crew = Crew(agents=[self.agent], tasks=[task], process=Process.sequential, verbose=True)  # type: ignore[call-arg]

        result = crew.kickoff()

        try:
            # Parse the result as JSON
            scored_jobs = json.loads(str(result))
            return scored_jobs
        except json.JSONDecodeError as _e:
            # Explicit failure — mark all jobs with error state
            return [
                {**j, "match_score": None, "score_error": True,
                 "score_error_reason": f"LLM output was not valid JSON: {str(_e)[:80]}"}
                for j in jobs
            ]


class ResumeOptimizerAgent:
    """Agent responsible for tailoring resumes for specific jobs"""
    
    def __init__(self, llm=None):
        self.llm = llm or LLMFactory.create_llm(temperature=0.5)
        self.agent = self._create_agent()
    
    def _create_agent(self) -> Agent:
        """Create the CrewAI agent"""
        prompts = AGENT_PROMPTS["resume_optimizer"]
        
        return Agent(
            role=prompts["role"],
            goal=prompts["goal"],
            backstory=prompts["backstory"],
            llm=self.llm,
            verbose=True,
            allow_delegation=False,
            max_iter=5
        )
    
    def create_task(self, base_resume: str, job_description: str, 
                   variant_type: str = "balanced") -> Task:
        """Create a resume optimization task"""
        prompts = AGENT_PROMPTS["resume_optimizer"]
        
        task_description = f"""
        {prompts["task"]}
        
        **Base Resume:**
        {base_resume}
        
        **Target Job Description:**
        {job_description}
        
        **Variant Type:** {variant_type}
        
        Generate an optimized resume as JSON with all the specified fields.
        """
        
        return Task(
            description=task_description,
            agent=self.agent,
            expected_output="JSON object with optimized resume and metadata"
        )
    
    def optimize_resume(self, base_resume: str, job_description: str,
                       variant_type: str = "balanced") -> Dict:
        """Optimize resume for a specific job"""
        task = self.create_task(base_resume, job_description, variant_type)
        crew = Crew(agents=[self.agent], tasks=[task], process=Process.sequential, verbose=True)  # type: ignore[call-arg]

        result = crew.kickoff()

        try:
            optimized = json.loads(str(result))
            return optimized
        except json.JSONDecodeError as _e:
            # Explicit failure — None score, not fabricated 70
            return {
                "optimized_resume_text": base_resume,
                "changes_made": [],
                "ats_score_estimate": None,
                "variant_type": variant_type,
                "optimization_error": True,
                "optimization_error_reason": f"LLM output was not valid JSON: {str(_e)[:80]}",
            }


class CoverLetterAgent:
    """Agent responsible for generating personalized cover letters"""
    
    def __init__(self, llm=None):
        self.llm = llm or LLMFactory.create_llm(temperature=0.7)  # Higher temp for creativity
        self.agent = self._create_agent()
    
    def _create_agent(self) -> Agent:
        """Create the CrewAI agent"""
        prompts = AGENT_PROMPTS["cover_letter"]
        
        return Agent(
            role=prompts["role"],
            goal=prompts["goal"],
            backstory=prompts["backstory"],
            llm=self.llm,
            verbose=True,
            allow_delegation=False,
            max_iter=5
        )
    
    def create_task(self, job: Dict, user_profile: Dict, 
                   resume_summary: str) -> Task:
        """Create a cover letter generation task"""
        prompts = AGENT_PROMPTS["cover_letter"]
        
        task_description = f"""
        {prompts["task"]}
        
        **Job Details:**
        - Company: {job.get('company', 'Unknown')}
        - Title: {job.get('title', 'Unknown')}
        - Description: {job.get('description', '')[:1000]}...
        
        **Candidate Profile:**
        - Name: {user_profile.get('name', 'Unknown')}
        - Background: {resume_summary}
        - Why interested: Aligns with career goals in AI/ML engineering
        
        Generate a compelling cover letter as JSON.
        """
        
        return Task(
            description=task_description,
            agent=self.agent,
            expected_output="JSON object with cover letter and metadata"
        )
    
    def generate_cover_letter(self, job: Dict, user_profile: Dict,
                            resume_summary: str) -> Dict:
        """Generate personalized cover letter"""
        task = self.create_task(job, user_profile, resume_summary)
        crew = Crew(agents=[self.agent], tasks=[task], process=Process.sequential, verbose=True)  # type: ignore[call-arg]

        result = crew.kickoff()

        try:
            cover_letter = json.loads(str(result))
            return cover_letter
        except json.JSONDecodeError as _e:
            # Flagged fallback — caller knows this is a template, not AI output
            return {
                "cover_letter": f"Dear Hiring Manager at {job.get('company', 'your company')},\n\n"
                               f"I am writing to express my interest in the {job.get('title', 'position')} role...",
                "word_count": 200,
                "tone": "professional",
                "generation_error": True,
                "generation_error_reason": f"LLM output was not valid JSON: {str(_e)[:80]}",
                "is_template_fallback": True,
            }


class QAValidatorAgent:
    """Agent responsible for quality assurance before submission"""
    
    def __init__(self, llm=None):
        self.llm = llm or LLMFactory.create_llm(temperature=0.1)  # Very low temp for consistency
        self.agent = self._create_agent()
    
    def _create_agent(self) -> Agent:
        """Create the CrewAI agent"""
        prompts = AGENT_PROMPTS["qa_validator"]
        
        return Agent(
            role=prompts["role"],
            goal=prompts["goal"],
            backstory=prompts["backstory"],
            llm=self.llm,
            verbose=True,
            allow_delegation=False,
            max_iter=3
        )
    
    def create_task(self, application_package: Dict) -> Task:
        """Create a validation task"""
        prompts = AGENT_PROMPTS["qa_validator"]
        
        task_description = f"""
        {prompts["task"]}
        
        **Application Package to Review:**
        {json.dumps(application_package, indent=2)}
        
        Provide validation results as JSON.
        """
        
        return Task(
            description=task_description,
            agent=self.agent,
            expected_output="JSON object with validation results"
        )
    
    def validate_application(self, application_package: Dict) -> Dict:
        """Validate application before submission"""
        task = self.create_task(application_package)
        crew = Crew(agents=[self.agent], tasks=[task], process=Process.sequential, verbose=True)  # type: ignore[call-arg]

        result = crew.kickoff()

        try:
            validation = json.loads(str(result))
            return validation
        except json.JSONDecodeError:
            # Default to approved if validation fails
            return {
                "validation_result": "llm_parse_error",
                "critical_issues": [],
                "warnings": [],
                "quality_score": 0,
                "human_review_required": True
            }
                # NOTE: LLM output was unparseable — not silently approved


class JobApplicationCrew:
    """Main crew that orchestrates all agents for job applications"""
    
    def __init__(self):
        self.job_finder = JobFinderAgent()
        self.resume_optimizer = ResumeOptimizerAgent()
        self.cover_letter_agent = CoverLetterAgent()
        self.qa_validator = QAValidatorAgent()
    
    def process_jobs(self, jobs: List[Dict], user_profile: Dict,
                    base_resume: str) -> List[Dict]:
        """
        Process jobs through the complete pipeline:
        1. Score and filter jobs
        2. Optimize resume for each job
        3. Generate cover letters
        4. Validate applications
        5. Return ready-to-submit applications
        """
        results = []
        
        # Step 1: Score jobs
        print("🔍 Scoring jobs...")
        scored_jobs = self.job_finder.score_jobs(jobs, user_profile)
        
        # Filter for high-score jobs only (≥75)
        high_score_jobs = [j for j in scored_jobs if j.get('score', 0) >= 75]
        print(f"✓ Found {len(high_score_jobs)} high-potential opportunities")
        
        # Step 2-4: Process each job
        for job in high_score_jobs[:settings.max_applications_per_day]:
            try:
                print(f"\n📄 Processing: {job.get('title')} at {job.get('company')}")
                
                # Optimize resume
                print("  ├─ Optimizing resume...")
                optimized_resume = self.resume_optimizer.optimize_resume(
                    base_resume,
                    job.get('description', ''),
                    variant_type="balanced"
                )
                
                # Generate cover letter
                print("  ├─ Generating cover letter...")
                cover_letter = self.cover_letter_agent.generate_cover_letter(
                    job,
                    user_profile,
                    resume_summary=base_resume[:500]
                )
                
                # Create application package
                application_package = {
                    "job": job,
                    "resume": optimized_resume,
                    "cover_letter": cover_letter,
                    "user_profile": user_profile
                }
                
                # Validate
                print("  ├─ Validating application...")
                validation = self.qa_validator.validate_application(application_package)
                
                if validation.get('validation_result') == 'approved':
                    print("  └─ ✓ Application ready")
                    results.append({
                        **application_package,
                        "validation": validation,
                        "status": "ready"
                    })
                else:
                    print(f"  └─ ⚠ {(validation.get('validation_result') or 'unknown').upper()}")
                    results.append({
                        **application_package,
                        "validation": validation,
                        "status": "flagged"
                    })
            
            except Exception as e:
                print(f"  └─ ✗ Error: {str(e)}")
                continue
        
        return results


# Example usage
if __name__ == "__main__":
    # Test the crew
    crew = JobApplicationCrew()
    
    # Sample data
    sample_jobs = [{
        "title": "AI Engineer",
        "company": "TechCorp",
        "description": "We need an AI engineer with LangChain and RAG experience...",
        "salary_max": 120000,
        "location": "Remote"
    }]
    
    sample_profile = {
        "name": "Satyam Shivam",
        "target_roles": ["AI Engineer", "ML Engineer"],
        "skills": {"primary": ["LangChain", "RAG", "Python"]},
        "locations": {"preferred": ["Remote"]},
        "salary": {"minimum_usd": 80000},
        "experience_level": "entry_level"
    }
    
    sample_resume = "AI Engineer with RAG and LangChain experience..."
    
    results = crew.process_jobs(sample_jobs, sample_profile, sample_resume)
    print(f"\n✓ Processed {len(results)} applications")
