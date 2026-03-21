export interface GeoJSONLayer {
  id: string
  name: string
  filePath: string
  visible: boolean
  data: any
  color: string
}

export interface MapViewState {
  center: [number, number]
  zoom: number
  bearing: number
  pitch: number
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: number
}

export interface Conversation {
  id: string
  title: string
  messages: ChatMessage[]
  createdAt: number
}

export interface MapAction {
  type: string
  payload: Record<string, any>
}

export interface ProjectData {
  version: 1
  mapState: MapViewState
  layers: Array<{
    name: string
    filePath: string
    visible: boolean
    color: string
  }>
  drawnFeatures: any[]
  conversations: Conversation[]
  activeConversationId: string | null
  chatHistory?: ChatMessage[]
  basemap: string
}

export interface MapContext {
  center: [number, number]
  zoom: number
  layers: Array<{
    name: string
    featureCount: number
    geometryTypes: string[]
    properties: string[]
    visible: boolean
  }>
  drawnFeatures: Array<{
    type: string
    coordinates_summary: string
  }>
  basemap: string
}

export const LAYER_COLORS = [
  '#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4',
  '#42d4f4', '#f032e6', '#bfef45', '#fabed4', '#469990',
]

export const BASEMAPS: Record<string, { name: string; tiles: string[]; attribution: string }> = {
  street: {
    name: 'Street',
    tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
    attribution: '&copy; OpenStreetMap contributors',
  },
  satellite: {
    name: 'Satellite',
    tiles: [
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    ],
    attribution: '&copy; Esri',
  },
  dark: {
    name: 'Dark',
    tiles: ['https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png'],
    attribution: '&copy; CartoDB',
  },
  terrain: {
    name: 'Terrain',
    tiles: ['https://tile.opentopomap.org/{z}/{x}/{y}.png'],
    attribution: '&copy; OpenTopoMap',
  },
}
