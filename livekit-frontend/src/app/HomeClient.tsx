"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import {
  LiveKitRoom,
  useVoiceAssistant,
  RoomAudioRenderer,
  useDataChannel,
} from "@livekit/components-react";

function getLiveKitUrl(): string {
  if (typeof window === "undefined") return "wss://localhost:3443/livekit-ws/";
  return `wss://${window.location.host}/livekit-ws/`;
}
const LIVEKIT_URL = getLiveKitUrl();
const TOKEN_URL = process.env.NEXT_PUBLIC_TOKEN_URL || "/api/token";

interface Voice {
  id: string;
  name: string;
  desc: string;
  lang: string;
  category: string;
}

const VOICES: Voice[] = [
  // --- Unmute Featured ---
  { id: "unmute-prod-website/default_voice.wav", name: "Default", desc: "Standard clear voice", lang: "EN", category: "Featured" },
  { id: "unmute-prod-website/p329_022.wav", name: "Watercooler", desc: "Casual conversation", lang: "EN", category: "Featured" },
  { id: "unmute-prod-website/ex04_narration_longform_00001.wav", name: "Narrator", desc: "Expressive storyteller", lang: "EN", category: "Featured" },
  { id: "unmute-prod-website/developer-1.mp3", name: "Dev", desc: "Tech news host", lang: "EN", category: "Featured" },
  { id: "unmute-prod-website/freesound/440565_why-is-there-educationwav.mp3", name: "Gertrude", desc: "Kind life advisor", lang: "EN", category: "Featured" },
  { id: "unmute-prod-website/freesound/519189_request-42---hmm-i-dont-knowwav.mp3", name: "Quiz Host", desc: "Skeptical British man", lang: "EN", category: "Featured" },
  { id: "unmute-prod-website/degaulle-2.wav", name: "Charles", desc: "Formal, historical", lang: "FR/EN", category: "Featured" },
  { id: "unmute-prod-website/fabieng-enhanced-v2.wav", name: "Fabieng", desc: "French startup coach", lang: "FR", category: "Featured" },

  // --- Alba MacKenna (Voice-acted characters) ---
  { id: "alba-mackenna/announcer.wav", name: "Announcer", desc: "Professional announcer", lang: "EN", category: "Characters" },
  { id: "alba-mackenna/casual.wav", name: "Casual", desc: "Relaxed everyday voice", lang: "EN", category: "Characters" },
  { id: "alba-mackenna/merchant.wav", name: "Merchant", desc: "Persuasive trader", lang: "EN", category: "Characters" },
  { id: "alba-mackenna/a-moment-by.wav", name: "Reflective", desc: "Thoughtful, poetic", lang: "EN", category: "Characters" },

  // --- Expresso (Emotional range) ---
  { id: "expresso/ex04-ex02_happy_001_channel1_118s.wav", name: "Happy", desc: "Cheerful and upbeat", lang: "EN", category: "Expressive" },
  { id: "expresso/ex03-ex01_calm_001_channel1_1143s.wav", name: "Calm", desc: "Soothing and relaxed", lang: "EN", category: "Expressive" },
  { id: "expresso/ex03-ex01_angry_001_channel1_201s.wav", name: "Intense", desc: "Forceful and direct", lang: "EN", category: "Expressive" },
  { id: "expresso/ex03-ex01_sarcastic_001_channel1_435s.wav", name: "Sarcastic", desc: "Witty and dry", lang: "EN", category: "Expressive" },
  { id: "expresso/ex04-ex02_confused_001_channel1_499s.wav", name: "Confused", desc: "Uncertain, questioning", lang: "EN", category: "Expressive" },
  { id: "expresso/ex03-ex02_narration_001_channel1_674s.wav", name: "Storyteller", desc: "Narrative, engaging", lang: "EN", category: "Expressive" },
  { id: "expresso/ex04-ex02_fearful_001_channel1_316s.wav", name: "Fearful", desc: "Nervous and tense", lang: "EN", category: "Expressive" },
  { id: "expresso/ex03-ex01_awe_001_channel1_1323s.wav", name: "Amazed", desc: "Wonderstruck", lang: "EN", category: "Expressive" },
  { id: "expresso/ex01-ex02_whisper_001_channel1_579s.wav", name: "Whisper", desc: "Soft and secretive", lang: "EN", category: "Expressive" },
  { id: "expresso/ex03-ex01_sleepy_001_channel1_619s.wav", name: "Sleepy", desc: "Drowsy and mellow", lang: "EN", category: "Expressive" },
  { id: "expresso/ex04-ex02_desire_001_channel1_657s.wav", name: "Desire", desc: "Warm and longing", lang: "EN", category: "Expressive" },
  { id: "expresso/ex01-ex02_fast_001_channel1_104s.wav", name: "Fast", desc: "Quick and energetic", lang: "EN", category: "Expressive" },

  // --- EARS (Emotional Audio) ---
  { id: "ears/p003/emo_neutral_freeform.wav", name: "EARS Neutral", desc: "Balanced, clear", lang: "EN", category: "EARS" },
  { id: "ears/p003/emo_amusement_freeform.wav", name: "EARS Amused", desc: "Light and playful", lang: "EN", category: "EARS" },
  { id: "ears/p003/emo_contentment_freeform.wav", name: "EARS Content", desc: "Satisfied, peaceful", lang: "EN", category: "EARS" },
  { id: "ears/p031/emo_pride_freeform.wav", name: "EARS Proud", desc: "Confident and strong", lang: "EN", category: "EARS" },
  { id: "ears/p031/emo_serenity_freeform.wav", name: "EARS Serene", desc: "Tranquil and smooth", lang: "EN", category: "EARS" },
  { id: "ears/p031/emo_interest_freeform.wav", name: "EARS Curious", desc: "Engaged, inquisitive", lang: "EN", category: "EARS" },

  // --- VCTK (Multi-accent English) ---
  { id: "vctk/p225_023.wav", name: "VCTK p225", desc: "F, 23, Southern English", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p226_023.wav", name: "VCTK p226", desc: "M, 22, Surrey", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p227_023.wav", name: "VCTK p227", desc: "M, 38, Cumbria", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p228_023.wav", name: "VCTK p228", desc: "F, 22, Southern English", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p230_023.wav", name: "VCTK p230", desc: "F, 22, Stockton-on-Tees", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p231_023.wav", name: "VCTK p231", desc: "F, 23, Southern English", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p232_023.wav", name: "VCTK p232", desc: "M, 23, Southern English", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p243_023.wav", name: "VCTK p243", desc: "M, 22, London", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p245_023.wav", name: "VCTK p245", desc: "M, 26, Irish", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p246_023.wav", name: "VCTK p246", desc: "M, 22, Scottish", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p248_023.wav", name: "VCTK p248", desc: "F, 23, Southern English", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p250_023.wav", name: "VCTK p250", desc: "F, 22, Southern English", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p254_023.wav", name: "VCTK p254", desc: "M, 26, South African", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p256_023.wav", name: "VCTK p256", desc: "M, 24, Northern English", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p259_023.wav", name: "VCTK p259", desc: "M, 23, Welsh", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p262_023.wav", name: "VCTK p262", desc: "F, 23, Scottish", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p267_023.wav", name: "VCTK p267", desc: "F, 23, Yorkshire", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p272_023.wav", name: "VCTK p272", desc: "M, 29, Scottish", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p278_023.wav", name: "VCTK p278", desc: "M, 22, Irish", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p286_023.wav", name: "VCTK p286", desc: "M, 22, New Zealand", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p300_023.wav", name: "VCTK p300", desc: "F, 23, American", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p306_023.wav", name: "VCTK p306", desc: "F, 24, American", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p312_023.wav", name: "VCTK p312", desc: "F, 21, Canadian", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p329_023.wav", name: "VCTK p329", desc: "F, 23, Southern English", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p345_023.wav", name: "VCTK p345", desc: "M, 24, American", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/p364_023.wav", name: "VCTK p364", desc: "M, 29, American", lang: "EN", category: "VCTK Accents" },
  { id: "vctk/s5_023.wav", name: "VCTK s5", desc: "M, Scottish", lang: "EN", category: "VCTK Accents" },

  // --- Community Voice Donations (CC0) ---
  { id: "voice-donations/AHmad.wav", name: "AHmad", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/ASEN.wav", name: "ASEN", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Aadi.wav", name: "Aadi", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/AbD.wav", name: "AbD", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Abhinox.wav", name: "Abhinox", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Abo_Ayman.wav", name: "Abo Ayman", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Abob_Malay.wav", name: "Abob Malay", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Adarsh_Bulla.wav", name: "Adarsh Bulla", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/AgentCobra.wav", name: "AgentCobra", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Ajith.wav", name: "Ajith", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Alejandro_espanol_latino.wav", name: "Alejandro", desc: "Community donation", lang: "ES", category: "Community" },
  { id: "voice-donations/Allen.wav", name: "Allen", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/AmitNag.wav", name: "Amit Nag", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Andrea.wav", name: "Andrea", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Andrea_(Spanish).wav", name: "Andrea (ES)", desc: "Community donation", lang: "ES", category: "Community" },
  { id: "voice-donations/Antoine_Vala.wav", name: "Antoine Vala", desc: "Community donation", lang: "FR", category: "Community" },
  { id: "voice-donations/Antoni.wav", name: "Antoni", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Aon.wav", name: "Aon", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Arjun_Z.wav", name: "Arjun Z", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Aryobe.wav", name: "Aryobe", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/BLUE.wav", name: "BLUE", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Bijay.wav", name: "Bijay", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Blake.wav", name: "Blake", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Bobby_McFern.wav", name: "Bobby McFern", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Breaking_1.wav", name: "Breaking 1", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/BrokenHypocrite.wav", name: "BrokenHypocrite", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Butter.wav", name: "Butter", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/CPS_001.wav", name: "CPS 001", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Chujus.wav", name: "Chujus", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Cicada.wav", name: "Cicada", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/ClassicWizard.wav", name: "ClassicWizard", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Curlinvictus.wav", name: "Curlinvictus", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Darius.wav", name: "Darius", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Darya_khan.wav", name: "Darya Khan", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Deepak.wav", name: "Deepak", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Dhruv_Rao.wav", name: "Dhruv Rao", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Dil.wav", name: "Dil", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Enrique.wav", name: "Enrique", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Enrique_(Spanish).wav", name: "Enrique (ES)", desc: "Community donation", lang: "ES", category: "Community" },
  { id: "voice-donations/Erick.wav", name: "Erick", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Ernesto_Y.wav", name: "Ernesto Y", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Eshan.wav", name: "Eshan", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Esteban_Aguirre_Arias.wav", name: "Esteban A.", desc: "Community donation", lang: "ES", category: "Community" },
  { id: "voice-donations/Ferdinand.wav", name: "Ferdinand", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/FlorDaddy.wav", name: "FlorDaddy", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Fred_Mara.wav", name: "Fred Mara", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Giovanne.wav", name: "Giovanne", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Glenn.wav", name: "Glenn", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Goku.wav", name: "Goku", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Gonzalo.wav", name: "Gonzalo", desc: "Community donation", lang: "ES", category: "Community" },
  { id: "voice-donations/Greggy.wav", name: "Greggy", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Haku.wav", name: "Haku", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Hannah.wav", name: "Hannah", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Hardik_Clone.wav", name: "Hardik", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Hillbilly_Jim.wav", name: "Hillbilly Jim", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Hugo_the_frenchie.wav", name: "Hugo", desc: "Community donation", lang: "FR", category: "Community" },
  { id: "voice-donations/Ilyass_yea.wav", name: "Ilyass", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Imran_from_I_India.wav", name: "Imran", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/James.wav", name: "James", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Jaspino.wav", name: "Jaspino", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Jay.wav", name: "Jay", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Jeff_Andrew.wav", name: "Jeff Andrew", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Jeffrey.wav", name: "Jeffrey", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Jeremy_Q.wav", name: "Jeremy Q", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Jimmy.wav", name: "Jimmy", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/John_Triguero.wav", name: "John Triguero", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Karti.wav", name: "Karti", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Koorosh.wav", name: "Koorosh", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/L_Roy.wav", name: "L Roy", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Lake.wav", name: "Lake", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Lammy.wav", name: "Lammy", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Lara.wav", name: "Lara", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Latin_Accent.wav", name: "Latin Accent", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Liquescent.wav", name: "Liquescent", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Louis.wav", name: "Louis", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Lucas.wav", name: "Lucas", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Maisako.wav", name: "Maisako", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Manahen.wav", name: "Manahen", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Midlands_Bedfordshire_Dialect.wav", name: "Midlands UK", desc: "Bedfordshire dialect", lang: "EN", category: "Community" },
  { id: "voice-donations/Moses.wav", name: "Moses", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/MrHat.wav", name: "MrHat", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Mr_captain.wav", name: "Mr Captain", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Mystery_Sir.wav", name: "Mystery Sir", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Narrum.wav", name: "Narrum", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Nick.wav", name: "Nick", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Parthiban.wav", name: "Parthiban", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Puzzle.wav", name: "Puzzle", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Qasim_Wali_Khan.wav", name: "Qasim W.K.", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Rahul.wav", name: "Rahul", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Ranjith.wav", name: "Ranjith", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Richard_cuban.wav", name: "Richard", desc: "Cuban accent", lang: "EN", category: "Community" },
  { id: "voice-donations/Rony.wav", name: "Rony", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Roscoe.wav", name: "Roscoe", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/STONE.wav", name: "STONE", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Samsewak.wav", name: "Samsewak", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Selfie.wav", name: "Selfie", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Sheddy.wav", name: "Sheddy", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Sir_TJ.wav", name: "Sir TJ", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Sr_Erick.wav", name: "Sr Erick", desc: "Community donation", lang: "ES", category: "Community" },
  { id: "voice-donations/TESLLA.wav", name: "TESLLA", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/TheFin.wav", name: "TheFin", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/The_Sustainabler.wav", name: "The Sustainabler", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Titorium.wav", name: "Titorium", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Tonmoy.wav", name: "Tonmoy", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Umair.wav", name: "Umair", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Victor_Garcia.wav", name: "Victor Garcia", desc: "Community donation", lang: "ES", category: "Community" },
  { id: "voice-donations/Vivaldi.wav", name: "Vivaldi", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/WhisperInEar.wav", name: "WhisperInEar", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/Yesid.wav", name: "Yesid", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/english_with_german_accent.wav", name: "German Accent", desc: "English with German accent", lang: "EN", category: "Community" },
  { id: "voice-donations/oldNerd.wav", name: "oldNerd", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/robert.wav", name: "Robert", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/siddharth_khanna.wav", name: "Siddharth K.", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/spanish-limaperu.wav", name: "Lima Peru", desc: "Peruvian Spanish", lang: "ES", category: "Community" },
  { id: "voice-donations/thepolishdane.wav", name: "The Polish Dane", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/vinayak.wav", name: "Vinayak", desc: "Community donation", lang: "EN", category: "Community" },
  { id: "voice-donations/zerocool.wav", name: "Zerocool", desc: "Community donation", lang: "EN", category: "Community" },
];

const CATEGORIES = [...new Set(VOICES.map((v) => v.category))];

interface TranscriptEntry {
  role: "user" | "agent";
  text: string;
  isFunctionCall?: boolean;
}

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [selectedVoice, setSelectedVoice] = useState(VOICES[0].id);
  const [activeCategory, setActiveCategory] = useState(CATEGORIES[0]);

  const handleConnect = useCallback(async () => {
    setConnecting(true);
    try {
      const resp = await fetch(`${TOKEN_URL}?voice=${encodeURIComponent(selectedVoice)}`);
      const data = await resp.json();
      setToken(data.token);
    } catch (e) {
      console.error("Failed to get token:", e);
      setConnecting(false);
    }
  }, [selectedVoice]);

  const handleDisconnect = useCallback(() => {
    setToken(null);
    setConnecting(false);
  }, []);

  const filteredVoices = VOICES.filter((v) => v.category === activeCategory);
  const selectedVoiceObj = VOICES.find((v) => v.id === selectedVoice);

  if (!token) {
    return (
      <div className="container">
        <h1>Unmute LiveKit</h1>
        <p className="subtitle">
          Voice AI with function calling. Try: &quot;What&apos;s the weather in Beverly Hills?&quot;
        </p>

        <div className="voice-selector">
          <label className="voice-label">
            Choose a voice:
            {selectedVoiceObj && (
              <span className="voice-selected-badge">
                {selectedVoiceObj.name} ({selectedVoiceObj.lang})
              </span>
            )}
          </label>

          <div className="category-tabs">
            {CATEGORIES.map((cat) => (
              <button
                key={cat}
                className={`category-tab ${activeCategory === cat ? "active" : ""}`}
                onClick={() => setActiveCategory(cat)}
              >
                {cat}
                <span className="category-count">
                  {VOICES.filter((v) => v.category === cat).length}
                </span>
              </button>
            ))}
          </div>

          <div className="voice-grid">
            {filteredVoices.map((voice) => (
              <button
                key={voice.id}
                className={`voice-card ${selectedVoice === voice.id ? "selected" : ""}`}
                onClick={() => setSelectedVoice(voice.id)}
              >
                <div className="voice-card-header">
                  <span className="voice-name">{voice.name}</span>
                  <span className="voice-lang">{voice.lang}</span>
                </div>
                <span className="voice-desc">{voice.desc}</span>
              </button>
            ))}
          </div>
        </div>

        <button
          className="connect-btn"
          onClick={handleConnect}
          disabled={connecting}
        >
          {connecting ? "Connecting..." : "Start Conversation"}
        </button>

        <p className="subtitle" style={{ fontSize: "0.75rem" }}>
          Kyutai STT/TTS + Qwen 3 4B (LM Studio) + LiveKit
        </p>
      </div>
    );
  }

  return (
    <LiveKitRoom
      serverUrl={LIVEKIT_URL}
      token={token}
      connect={true}
      audio={true}
      onDisconnected={handleDisconnect}
    >
      <RoomAudioRenderer />
      <VoiceAssistantUI onDisconnect={handleDisconnect} />
    </LiveKitRoom>
  );
}

function VoiceAssistantUI({ onDisconnect }: { onDisconnect: () => void }) {
  const { state } = useVoiceAssistant();
  const [transcripts, setTranscripts] = useState<TranscriptEntry[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  const onDataReceived = useCallback(
    (payload: Uint8Array) => {
      try {
        const text = new TextDecoder().decode(payload);
        const msg = JSON.parse(text);
        if (msg.type === "transcript") {
          setTranscripts((prev) => [
            ...prev,
            { role: msg.role, text: msg.text, isFunctionCall: msg.isFunctionCall },
          ]);
        }
      } catch {
        // ignore
      }
    },
    []
  );

  useDataChannel("transcripts", onDataReceived);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [transcripts]);

  const statusText =
    state === "listening" ? "Listening..."
    : state === "thinking" ? "Thinking..."
    : state === "speaking" ? "Speaking..."
    : state === "connecting" ? "Connecting..."
    : "Connected";

  const dotClass =
    state === "disconnected" ? "disconnected" : state === "connecting" ? "connecting" : "";

  return (
    <div className="container">
      <h1>Unmute LiveKit</h1>
      <div className="status">
        <span className={`status-dot ${dotClass}`} />
        {statusText}
      </div>
      <div className="transcript-box" ref={scrollRef}>
        {transcripts.length === 0 && (
          <p style={{ color: "#555" }}>
            Start talking... Try &quot;What&apos;s the weather in Beverly Hills?&quot;
          </p>
        )}
        {transcripts.map((entry, i) => (
          <div key={i} className="transcript-entry">
            <span className={`role ${entry.role}`}>
              {entry.role === "user" ? "You:" : "Agent:"}
            </span>
            {entry.text}
            {entry.isFunctionCall && (
              <div className="weather-badge">Weather lookup</div>
            )}
          </div>
        ))}
      </div>
      <button className="disconnect-btn" onClick={onDisconnect}>
        End Conversation
      </button>
    </div>
  );
}
