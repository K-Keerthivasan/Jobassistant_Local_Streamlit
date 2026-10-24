from resume_gen.models import TargetRole
from resume_gen.personas import auto_select, select_persona, is_visual_ai_role

def test_visual_ai_artist_does_not_route_to_llm_engineering():
    t=TargetRole(company='Cineflix',title='AI Artist',description='AI agents, local models, automation, LoRA and compositing for video')
    assert is_visual_ai_role(t)
    assert auto_select(t)['id']=='content_video'
    assert select_persona(t)['id']=='content_video'
    assert not is_visual_ai_role(TargetRole(company='Example',title='AI Engineer',description='LLM automation'))
