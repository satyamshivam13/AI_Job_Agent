"""
Database initialization script
Creates tables and sets up initial data
"""

import sys
from pathlib import Path
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from models.database import Base, UserProfile, Job, Application, ResumeVersion
from utils.logger import logger


def init_database():
    """Initialize database with tables"""
    logger.info("🔧 Initializing database...")
    
    try:
        # Create engine
        engine = create_engine(settings.database_url)
        
        # Create all tables
        Base.metadata.create_all(engine)
        
        # Verify tables were created
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        logger.info(f"✓ Created {len(tables)} tables:")
        for table in tables:
            logger.info(f"  - {table}")
        
        # Create session
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Check if user profile exists
        existing_profile = session.query(UserProfile).first()
        
        if not existing_profile:
            logger.info("📝 Creating default user profile...")
            
            # Create default profile from Satyam's resume
            profile = UserProfile(
                full_name="Satyam Shivam",
                email="shivamsatyam35@gmail.com",
                phone="+91 9852015381",
                location="New Delhi, India",
                linkedin_url="https://linkedin.com/in/satyam",
                github_url="https://github.com/satyam",
                portfolio_url="https://portfolio.example.com",
                target_roles=["AI Engineer", "ML Engineer", "GenAI Developer", "LLM Engineer"],
                skills_primary=["LangChain", "RAG", "OpenAI API", "CrewAI", "FastAPI", "Python", "Docker"],
                skills_secondary=["AWS", "PostgreSQL", "FAISS", "ChromaDB", "React", "Node.js"],
                preferred_locations=["Remote", "New Delhi", "Bangalore", "Hyderabad"],
                willing_to_relocate=["USA", "Canada", "Europe", "Singapore"],
                remote_preference="preferred",
                minimum_salary_usd=80000,
                minimum_salary_inr=800000,
                currency_preference="USD",
                work_authorization=["India"],
                visa_sponsorship_required=True,
                experience_level="entry_level",
                company_size_pref=["startup", "mid_size", "enterprise"],
                company_stage_pref=["series_a", "series_b", "series_c", "public"],
                base_resume_path="/mnt/user-data/uploads/Satyam_Resume.pdf"
            )
            
            session.add(profile)
            session.commit()
            
            logger.info(f"✓ Created user profile for {profile.full_name}")
        else:
            logger.info(f"✓ User profile already exists: {existing_profile.full_name}")
        
        session.close()
        
        logger.info("✅ Database initialization complete!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {str(e)}")
        return False


def reset_database():
    """Drop all tables and recreate (USE WITH CAUTION)"""
    logger.warning("⚠️ RESETTING DATABASE - ALL DATA WILL BE LOST!")
    
    response = input("Type 'YES' to confirm: ")
    if response != "YES":
        logger.info("Cancelled.")
        return
    
    try:
        engine = create_engine(settings.database_url)
        Base.metadata.drop_all(engine)
        logger.info("✓ Dropped all tables")
        
        init_database()
        
    except Exception as e:
        logger.error(f"❌ Reset failed: {str(e)}")


def show_database_stats():
    """Show database statistics"""
    logger.info("📊 Database Statistics")
    
    try:
        engine = create_engine(settings.database_url)
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Count records in each table
        job_count = session.query(Job).count()
        app_count = session.query(Application).count()
        resume_count = session.query(ResumeVersion).count()
        profile_count = session.query(UserProfile).count()
        
        logger.info(f"  Jobs: {job_count}")
        logger.info(f"  Applications: {app_count}")
        logger.info(f"  Resume Versions: {resume_count}")
        logger.info(f"  User Profiles: {profile_count}")
        
        # Recent activity
        recent_jobs = session.query(Job).order_by(Job.scraped_at.desc()).limit(5).all()
        
        if recent_jobs:
            logger.info("\n🔥 Recent Jobs:")
            for job in recent_jobs:
                logger.info(f"  - {job.title} at {job.company} ({job.platform})")
        
        session.close()
        
    except Exception as e:
        logger.error(f"❌ Failed to get stats: {str(e)}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Database management')
    parser.add_argument('action', choices=['init', 'reset', 'stats'], 
                       help='Action to perform')
    
    args = parser.parse_args()
    
    if args.action == 'init':
        init_database()
    elif args.action == 'reset':
        reset_database()
    elif args.action == 'stats':
        show_database_stats()
