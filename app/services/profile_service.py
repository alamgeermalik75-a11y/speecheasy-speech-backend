from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.profile import Profile, FocusSound
from app.schemas.profile import ProfileCreateOrUpdate
from app.core.exceptions import NotFoundException

class ProfileService:
    @staticmethod
    async def get_profile(session: AsyncSession, patient_uid: str) -> Profile:
        stmt = (
            select(Profile)
            .where(Profile.patient_uid == patient_uid)
            .options(selectinload(Profile.focus_sound))
        )
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()
        if not profile:
            raise NotFoundException("Profile not found")
        return profile

    @staticmethod
    async def upsert_profile(
        session: AsyncSession,
        patient_uid: str,
        data: ProfileCreateOrUpdate
    ) -> Profile:
        stmt = (
            select(Profile)
            .where(Profile.patient_uid == patient_uid)
            .options(selectinload(Profile.focus_sound))
        )
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()

        if profile:
            # Update existing profile
            profile.parent_name = data.parent_name
            profile.child_name = data.child_name
            if data.phone is not None:
                profile.phone = data.phone
            if data.age is not None:
                profile.age = data.age

            # Update or preserve focus sound
            if data.sound and data.alphabet_name:
                if profile.focus_sound:
                    # Update sound and alphabet but PRESERVE existing progress
                    profile.focus_sound.sound = data.sound
                    profile.focus_sound.alphabet_name = data.alphabet_name
                else:
                    focus = FocusSound(
                        patient_uid=patient_uid,
                        sound=data.sound,
                        alphabet_name=data.alphabet_name,
                        progress=0.0
                    )
                    session.add(focus)
                    profile.focus_sound = focus
        else:
            # Create new profile
            profile = Profile(
                patient_uid=patient_uid,
                parent_name=data.parent_name,
                child_name=data.child_name,
                age=data.age,
                phone=data.phone
            )
            session.add(profile)
            await session.flush()

            if data.sound and data.alphabet_name:
                focus = FocusSound(
                    patient_uid=patient_uid,
                    sound=data.sound,
                    alphabet_name=data.alphabet_name,
                    progress=0.0
                )
                session.add(focus)
                profile.focus_sound = focus

        await session.commit()

        # Re-query clean committed profile with eager-loaded focus_sound
        return await ProfileService.get_profile(session, patient_uid)

    @staticmethod
    async def delete_profile(session: AsyncSession, patient_uid: str) -> bool:
        stmt = select(Profile).where(Profile.patient_uid == patient_uid)
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()
        if not profile:
            raise NotFoundException("Profile not found")

        await session.delete(profile)
        await session.commit()
        return True
