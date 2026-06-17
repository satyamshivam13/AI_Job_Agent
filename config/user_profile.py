"""
User Profile Helper
Loads and returns the user profile from the JSON config file.
"""
import json
from pathlib import Path
from typing import Dict, Any

_PROFILE_PATH = Path(__file__).parent / "user_profile.json"


def get_user_profile(user_id: str = None) -> Dict[str, Any]:
    """
    Return user profile dict.
    In production, user_id would be used to load from database.
    For the single-user case, loads from config/user_profile.json.
    """
    try:
        with open(_PROFILE_PATH) as f:
            profile = json.load(f)
        return profile
    except FileNotFoundError:
        # Safe fallback profile
        return {
            "name": "Unknown User",
            "email": "",
            "skills": [],
            "target_roles": [],
            "locations": {"preferred": []},
            "salary": {"minimum_usd": 0},
            "experience_level": "entry_level",
            "base_resume": "",
        }
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid user_profile.json: {e}") from e
