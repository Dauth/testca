package game

const (
	EnemyGrunt    uint8 = 1
	EnemyRunner   uint8 = 2
	EnemyTank     uint8 = 3
	EnemyKamikaze uint8 = 4
	EnemyBoss     uint8 = 5
)

var RoomTemplates = [11]*RoomTemplate{
	nil,

	{
		TilemapID: "room-1",
	},

	{
		TilemapID: "room-2",
	},

	{
		TilemapID: "room-3",
	},

	{
		TilemapID: "room-4",
	},

	{
		TilemapID: "room-5",
	},

	{
		TilemapID: "room-6",
	},

	{
		TilemapID: "room-7",
	},

	{
		TilemapID: "room-8",
	},

	{
		TilemapID: "room-9",
	},

	{
		TilemapID: "room-10",
	},
}

