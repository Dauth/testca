package game

type ShopOffer struct {
	ID   uint8
	Name string
	Cost int32
}

const (
	ShopItemAmmo     uint8 = 1
	ShopItemSpeed    uint8 = 2
	ShopItemFireRate uint8 = 3
	ShopItemDamage   uint8 = 4
)

var ShopCatalog = []ShopOffer{
	{ID: ShopItemAmmo, Name: "ammo", Cost: 5},
	{ID: ShopItemSpeed, Name: "speed", Cost: 10},
	{ID: ShopItemFireRate, Name: "fire_rate", Cost: 15},
	{ID: ShopItemDamage, Name: "damage", Cost: 20},
}

func HandleShopPurchase(p *PlayerState, itemID uint8) bool {
	if itemID == 0 || int(itemID) > len(ShopCatalog) {
		return false
	}
	offer := ShopCatalog[itemID-1]
	if p.Coins < offer.Cost {
		return false
	}
	p.Coins -= offer.Cost

	switch offer.ID {
	case ShopItemAmmo:

		for w, spec := range WeaponSpecs {
			if spec.AmmoMax >= 9999 {
				continue
			}
			p.WeaponAmmo[w] = spec.AmmoMax
		}
	case ShopItemSpeed:
		p.SpeedStacks++
	case ShopItemFireRate:
		p.FireRateStacks++
	case ShopItemDamage:
		p.DamageStacks++
	default:

		p.Coins += offer.Cost
		return false
	}
	return true
}

